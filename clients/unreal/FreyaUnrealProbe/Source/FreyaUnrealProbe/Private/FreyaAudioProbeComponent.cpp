#include "FreyaAudioProbeComponent.h"
#include "FreyaLink.h"
#include "HAL/PlatformMisc.h"
#include <atomic>
#include "MetaHumanAudioBaseLiveLinkSubject.h"
#include "MetaHumanAudioBaseLiveLinkSubjectSettings.h"
#include "MetaHumanLocalLiveLinkSource.h"
#include "ILiveLinkClient.h"
#include "LiveLinkTypes.h"
#include "Roles/LiveLinkBasicRole.h"
#include "Components/AudioComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Actor.h"
#include "UObject/UnrealType.h"
#include "Sound/SoundWaveProcedural.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "GameFramework/GameUserSettings.h"
#include "GenericPlatform/GenericApplication.h"
#include "HAL/PlatformApplicationMisc.h"
#include "Features/IModularFeatures.h"
#include "Misc/CommandLine.h"
#include "UnrealClient.h"
#include "Kismet/KismetSystemLibrary.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "Misc/ScopeLock.h"
#include "Serialization/Archive.h"

DEFINE_LOG_CATEGORY_STATIC(LogFreyaProbe, Log, All);

namespace
{
    constexpr int32 FixtureSampleRate = 24000;
    constexpr int32 MaxFixtureSeconds = 30;
    // How long after the last audio the solver is given to finish, before the final report.
    constexpr double TailSeconds = 1.0;
}

// Audio waiting to be fed to the solver, a little at a time at the pace it would
// be heard. The sampler thread owns the cursor; everything else only adds or clears.
class FFreyaProbeSubject final : public FMetaHumanAudioBaseLiveLinkSubject
{
public:
    FFreyaProbeSubject(ILiveLinkClient* Client, const FGuid& Id, FName Name,
                      UMetaHumanAudioBaseLiveLinkSubjectSettings* Settings)
        : FMetaHumanAudioBaseLiveLinkSubject(Client, Id, Name, Settings) {}

    void Push(const float* Data, int32 Count)
    {
        FScopeLock Guard(&Mutex);
        // Forget what has been fed already, so a long conversation does not pile up.
        if (Cursor > 0 && (Cursor == Fixture.Num() || Cursor > 10 * FixtureSampleRate))
        {
            Fixture.RemoveAt(0, Cursor, EAllowShrinking::No);
            Cursor = 0;
        }
        Fixture.Append(Data, Count);
    }

    // Drop whatever has not been fed yet. What the solver already has plays out.
    void Cancel()
    {
        FScopeLock Guard(&Mutex);
        Fixture.Reset();
        Cursor = 0;
    }

    int32 SolverFrames() const { return Frames.load(); }

protected:
    virtual void MediaSamplerMain() override
    {
        double Deadline = FPlatformTime::Seconds();
        while (IsRunning())
        {
            FAudioSample Packet;
            {
                FScopeLock Guard(&Mutex);
                const int32 Count = FMath::Min(480, Fixture.Num() - Cursor);
                if (Count > 0)
                {
                    Packet.Data.Append(Fixture.GetData() + Cursor, Count);
                    Cursor += Count;
                    Packet.NumSamples = Count;
                }
            }
            if (Packet.NumSamples <= 0)
            {
                Deadline = FPlatformTime::Seconds();
                FPlatformProcess::SleepNoStats(0.002f);
                continue;
            }
            Packet.NumChannels = 1;
            Packet.SampleRate = FixtureSampleRate;
            GetSampleTime(FFrameRate(60, 1), Packet.Time, Packet.TimeSource);
            const double Duration = Packet.NumSamples / double(FixtureSampleRate);
            AddAudioSample(MoveTemp(Packet));
            Deadline = FMath::Max(Deadline, FPlatformTime::Seconds()) + Duration;
            FPlatformProcess::SleepNoStats(float(FMath::Max(0.0, Deadline - FPlatformTime::Seconds())));
        }
    }

    // Called with each result the solver produces. Counting them is the plainest
    // evidence that the solver ran at all.
    virtual void ExtractPipelineData(TSharedPtr<UE::MetaHuman::Pipeline::FPipelineData> Data) override
    {
        ++Frames;
        FMetaHumanAudioBaseLiveLinkSubject::ExtractPipelineData(Data);
    }

private:
    FCriticalSection Mutex;
    TArray<float> Fixture;
    int32 Cursor = 0;
    std::atomic<int32> Frames{0};
};

class FFreyaProbeSource final : public FMetaHumanLocalLiveLinkSource
{
public:
    virtual FText GetSourceType() const override { return FText::FromString(TEXT("Freya fixture probe")); }
    bool Push(const float* Data, int32 Count)
    {
        if (!Subject.IsValid()) return false;
        Subject->Push(Data, Count);
        return true;
    }
    void Cancel() { if (Subject.IsValid()) Subject->Cancel(); }
    int32 SolverFrames() const { return Subject.IsValid() ? Subject->SolverFrames() : 0; }
protected:
    virtual TSharedPtr<FMetaHumanLocalLiveLinkSubject> CreateSubject(
        const FName& Name, UMetaHumanLocalLiveLinkSubjectSettings* InSubjectSettings) override
    {
        Subject = MakeShared<FFreyaProbeSubject>(LiveLinkClient, SourceGuid, Name,
            CastChecked<UMetaHumanAudioBaseLiveLinkSubjectSettings>(InSubjectSettings));
        return Subject;
    }
private:
    TSharedPtr<FFreyaProbeSubject> Subject;
};

UFreyaAudioProbeComponent::UFreyaAudioProbeComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;
}

void UFreyaAudioProbeComponent::BeginPlay()
{
    Super::BeginPlay();
    // An ordinary resizable window, never the whole screen, unless -fullscreen is given.
    // Settings saved by an earlier run are overridden, so this holds every time.
    if (!GIsEditor && !FParse::Param(FCommandLine::Get(), TEXT("fullscreen")))
        if (UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr)
        {
            // Sized from the display, not fixed: about three fifths of its usable
            // height, in a portrait shape. Unreal multiplies by the display's scale
            // itself, so the size is given in unscaled units.
            FDisplayMetrics Display;
            FDisplayMetrics::RebuildDisplayMetrics(Display);
            const FPlatformRect& Area = Display.PrimaryDisplayWorkAreaRect;
            const float Scale = FMath::Max(1.0f,
                FPlatformApplicationMisc::GetDPIScaleFactorAtPoint(Area.Left + 10.0f, Area.Top + 10.0f));
            const int32 Height = FMath::Clamp(FMath::RoundToInt((Area.Bottom - Area.Top) * 0.6f / Scale), 320, 1400);
            FIntPoint Size(FMath::RoundToInt(Height * 0.8f), Height);
            FParse::Value(FCommandLine::Get(), TEXT("ResX="), Size.X);
            FParse::Value(FCommandLine::Get(), TEXT("ResY="), Size.Y);
            Settings->SetFullscreenMode(EWindowMode::Windowed);
            Settings->SetScreenResolution(Size);
            Settings->SetFrameRateLimit(60.0f);
            Settings->ApplySettings(false);
        }
    // Started by Freya: she gives the port of her gateway and a key that works once.
    const FString GatewayPort = FPlatformMisc::GetEnvironmentVariable(TEXT("FREYA_GATEWAY_PORT"));
    const FString PairingKey = FPlatformMisc::GetEnvironmentVariable(TEXT("FREYA_PAIRING_KEY"));
    if (!GatewayPort.IsEmpty() && !PairingKey.IsEmpty() && FCString::Atoi(*GatewayPort) > 0)
    {
        const bool bLinked = InitializeProbe();
        UE_LOG(LogFreyaProbe, Display, TEXT("Started by Freya; probe %s. Connecting to her gateway."),
            bLinked ? TEXT("initialized") : TEXT("FAILED to initialize"));
        Link = MakeShared<FFreyaLink>(this, FCString::Atoi(*GatewayPort), PairingKey);
        Link->Start();
        return;
    }
    if (!bAutoStart) return;
    const bool bReady = InitializeProbe();
    UE_LOG(LogFreyaProbe, Display, TEXT("Auto start: probe %s. Fixture begins in %.1f s."),
        bReady ? TEXT("initialized") : TEXT("FAILED to initialize"), AutoStartDelaySeconds);
    if (bReady)
        GetWorld()->GetTimerManager().SetTimer(AutoStartTimer, this,
            &UFreyaAudioProbeComponent::AutoStart, FMath::Clamp(AutoStartDelaySeconds, 0.5f, 30.0f), false);
}

void UFreyaAudioProbeComponent::AutoStart()
{
    FString Path = FixturePath;
    FParse::Value(FCommandLine::Get(), TEXT("FreyaFixture="), Path);
    // One attempt only. A failure is reported, not retried.
    if (!StartFixture(Path))
        UE_LOG(LogFreyaProbe, Error, TEXT("RESULT: the fixture could not be started: %s"), *Path);
}

bool UFreyaAudioProbeComponent::InitializeProbe()
{
    if (Source.IsValid()) return true;
    if (SubjectName.IsNone() || !IModularFeatures::Get().IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName)) return false;
    ILiveLinkClient& Client = IModularFeatures::Get().GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName);
    Source = MakeShared<FFreyaProbeSource>();
    SourceId = Client.AddSource(Source);
    auto* Settings = NewObject<UMetaHumanAudioBaseLiveLinkSubjectSettings>(GetTransientPackage());
    Settings->Lookahead = FMath::Clamp(LookaheadMilliseconds, 80, 240);
    Settings->Setup();
    const auto Key = Source->RequestSubjectCreation(SubjectName.ToString(), Settings);
    if (!SourceId.IsValid() || !Key.Source.IsValid()) { StopProbe(); return false; }
    UE_LOG(LogFreyaProbe, Display, TEXT("Source registered. This does not prove solver readiness or output."));
    return true;
}

// The assembled MetaHuman's face reads Live Link through Epic's ABP_MH_LiveLink
// animation blueprint, which names its subject in a variable. Report what the face
// is using and, when asked to, point it at this probe's subject.
void UFreyaAudioProbeComponent::ConfigureFace()
{
    AActor* Owner = GetOwner();
    if (!Owner) return;
    TArray<USkeletalMeshComponent*> Meshes;
    Owner->GetComponents(Meshes);
    for (USkeletalMeshComponent* Mesh : Meshes)
    {
        if (Mesh->GetFName() != FaceComponentName) continue;
        UAnimInstance* Anim = Mesh->GetAnimInstance();
        UE_LOG(LogFreyaProbe, Display, TEXT("Face animation before: %s"), *GetNameSafe(Anim ? Anim->GetClass() : nullptr));
        if (bDriveFaceDirectly)
        {
            UClass* Wanted = LoadClass<UAnimInstance>(nullptr, TEXT("/MetaHumanCharacter/Animation/ABP_MH_LiveLink.ABP_MH_LiveLink_C"));
            if (!Wanted)
            {
                UE_LOG(LogFreyaProbe, Error, TEXT("The MetaHuman Live Link animation blueprint could not be loaded."));
            }
            else if (!Anim || !Anim->IsA(Wanted))
            {
                Mesh->SetAnimInstanceClass(Wanted);
                Anim = Mesh->GetAnimInstance();
            }
        }
        if (!Anim) continue;
        FStructProperty* Subject = FindFProperty<FStructProperty>(Anim->GetClass(), TEXT("LLink_Face_Subj"));
        FNameProperty* Name = Subject ? FindFProperty<FNameProperty>(Subject->Struct, TEXT("Name")) : nullptr;
        if (!Name)
        {
            UE_LOG(LogFreyaProbe, Warning, TEXT("Face animation %s has no Live Link subject variable."), *GetNameSafe(Anim->GetClass()));
            continue;
        }
        void* Value = Subject->ContainerPtrToValuePtr<void>(Anim);
        const FName Before = Name->GetPropertyValue_InContainer(Value);
        if (bDriveFaceDirectly) Name->SetPropertyValue_InContainer(Value, SubjectName);
        UE_LOG(LogFreyaProbe, Display, TEXT("Face animation now: %s, subject was '%s', is '%s'."),
            *GetNameSafe(Anim->GetClass()), *Before.ToString(), *Name->GetPropertyValue_InContainer(Value).ToString());
    }
}

bool UFreyaAudioProbeComponent::StartFixture(const FString& Path)
{
    constexpr int64 Limit = int64(MaxFixtureSeconds) * FixtureSampleRate * sizeof(float);
    const FString AbsolutePath = FPaths::IsRelative(Path)
        ? FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), Path) : Path;
    TUniquePtr<FArchive> Reader(IFileManager::Get().CreateFileReader(*AbsolutePath));
    if (!Reader) return false;
    const int64 Size = Reader->TotalSize();
    if (Size <= 0 || Size > Limit || Size % sizeof(float) != 0) return false;
    TArray<uint8> Bytes;
    Bytes.SetNumUninitialized(static_cast<int32>(Size));
    Reader->Serialize(Bytes.GetData(), Size);
    if (Reader->IsError()) return false;
    TArray<float> Samples;
    Samples.SetNumUninitialized(Bytes.Num() / sizeof(float));
    FMemory::Memcpy(Samples.GetData(), Bytes.GetData(), Bytes.Num());
    for (float Sample : Samples)
        if (!FMath::IsFinite(Sample) || FMath::Abs(Sample) > 1.0f) return false;

    TArray<int16> Pcm;
    Pcm.SetNumUninitialized(Samples.Num());
    for (int32 Index = 0; Index < Samples.Num(); ++Index)
        Pcm[Index] = static_cast<int16>(FMath::Clamp(FMath::RoundToInt(Samples[Index] * 32767.0f), -32768, 32767));
    const double Seconds = Samples.Num() / double(FixtureSampleRate);

    if (!BeginSpeech(FixtureSampleRate, bPlayAudibly ? Volume : 0.0f)) return false;
    PushSpeech(Pcm.GetData(), Pcm.Num());

    PeakCurve = 0.0f;
    CurvesAtPeak = 0;
    FixtureSeconds = Seconds;
    FixtureStartedAt = FPlatformTime::Seconds();
    LastReportAt = FixtureStartedAt;
    bFixtureActive = true;
    ShotsTaken = 0;
    bTakeShots = FParse::Param(FCommandLine::Get(), TEXT("FreyaShots"));
    UE_LOG(LogFreyaProbe, Display, TEXT("Fixture started: %.2f s, solver frames so far %d."),
        Seconds, GetSolverFrameCount());
    return true;
}

// Begin one utterance. The sound is given to the solver at full level; Loudness
// applies only to what is heard.
bool UFreyaAudioProbeComponent::BeginSpeech(int32 SampleRate, float Loudness)
{
    // The solver is fed at one rate. Anything else is refused, not resampled.
    if (SampleRate != FixtureSampleRate || !GetOwner() || !InitializeProbe()) return false;
    StopAudiblePlayback();
    Source->Cancel();
    ConfigureFace();

    Wave = NewObject<USoundWaveProcedural>(this);
    Wave->SetSampleRate(FixtureSampleRate);
    Wave->NumChannels = 1;
    Wave->Duration = INDEFINITELY_LOOPING_DURATION;
    Wave->SoundGroup = SOUNDGROUP_Voice;
    Wave->bLooping = false;
    SpeechVolume = FMath::Clamp(Loudness, 0.0f, 1.0f);
    SpeechSamples = 0;
    SpeechStartedAt = 0.0;
    bVoiceStarted = false;
    bSpeechOpen = true;
    return true;
}

void UFreyaAudioProbeComponent::PushSpeech(const int16* Samples, int32 Count)
{
    // At most what Freya ever sends for one utterance.
    if (!bSpeechOpen || !Samples || Count <= 0 || !Source.IsValid() || !Wave) return;
    if (SpeechSamples + Count > int64(MaxFixtureSeconds) * FixtureSampleRate) return;

    TArray<float> Floats;
    Floats.SetNumUninitialized(Count);
    for (int32 Index = 0; Index < Count; ++Index) Floats[Index] = Samples[Index] / 32768.0f;
    Source->Push(Floats.GetData(), Count);
    Wave->QueueAudio(reinterpret_cast<const uint8*>(Samples), Count * sizeof(int16));
    SpeechSamples += Count;

    // The sound starts a moment after the solver is first fed, so lips and voice agree.
    if (!bVoiceStarted && GetWorld() && !GetWorld()->GetTimerManager().IsTimerActive(PlaybackTimer))
    {
        const float Delay = FMath::Clamp(AudibleDelayMilliseconds, 0, 500) / 1000.0f;
        if (Delay <= 0.0f) BeginAudiblePlayback();
        else GetWorld()->GetTimerManager().SetTimer(PlaybackTimer, this,
            &UFreyaAudioProbeComponent::BeginAudiblePlayback, Delay, false);
    }
}

// True from the first sound queued until it has all been heard.
bool UFreyaAudioProbeComponent::IsSpeechAudible() const
{
    if (!bSpeechOpen || SpeechSamples <= 0) return false;
    if (!bVoiceStarted) return true;
    return FPlatformTime::Seconds() < SpeechStartedAt + SpeechSamples / double(FixtureSampleRate) + 0.25;
}

void UFreyaAudioProbeComponent::BeginAudiblePlayback()
{
    if (!bSpeechOpen || !Wave || !GetOwner()) return;
    bVoiceStarted = true;
    SpeechStartedAt = FPlatformTime::Seconds();

    if (!Voice)
    {
        Voice = NewObject<UAudioComponent>(GetOwner());
        Voice->bAutoDestroy = false;
        Voice->bAllowSpatialization = false;
        Voice->bIsUISound = true;
        Voice->RegisterComponent();
    }
    Voice->SetSound(Wave);
    // Never exactly zero: Unreal stops a silent sound, and its timing would be lost.
    Voice->SetVolumeMultiplier(FMath::Max(SpeechVolume, 0.0001f));
    Voice->Play();
}

void UFreyaAudioProbeComponent::StopAudiblePlayback()
{
    if (GetWorld()) GetWorld()->GetTimerManager().ClearTimer(PlaybackTimer);
    if (Voice) Voice->Stop();
    if (Wave) Wave->ResetAudio();
    bSpeechOpen = false;
    bVoiceStarted = false;
    SpeechSamples = 0;
}

void UFreyaAudioProbeComponent::CancelSpeech()
{
    if (GetWorld()) GetWorld()->GetTimerManager().ClearTimer(AutoStartTimer);
    if (Source.IsValid()) Source->Cancel();
    StopAudiblePlayback();
    if (bFixtureActive)
    {
        UE_LOG(LogFreyaProbe, Display, TEXT("Speech cancelled after %.2f s."),
            FPlatformTime::Seconds() - FixtureStartedAt);
        Report(true);
    }
}

int32 UFreyaAudioProbeComponent::GetSolverFrameCount() const
{
    return Source.IsValid() ? Source->SolverFrames() : 0;
}

void UFreyaAudioProbeComponent::TickComponent(float DeltaTime, ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    if (Link.IsValid()) Link->Tick();
    if (!bFixtureActive) return;

    // Read what the subject is publishing, the same values the face would use.
    if (IModularFeatures::Get().IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
    {
        ILiveLinkClient& Client = IModularFeatures::Get().GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName);
        FLiveLinkSubjectFrameData Frame;
        if (Client.EvaluateFrame_AnyThread(SubjectName, ULiveLinkBasicRole::StaticClass(), Frame))
        {
            if (const FLiveLinkBaseFrameData* Base = Frame.FrameData.GetBaseData())
            {
                float Largest = 0.0f;
                for (const float Value : Base->PropertyValues) Largest = FMath::Max(Largest, FMath::Abs(Value));
                if (Largest > PeakCurve) { PeakCurve = Largest; CurvesAtPeak = Base->PropertyValues.Num(); }
            }
        }
    }

    const double Now = FPlatformTime::Seconds();
    // With -FreyaShots, save a picture of what is on screen at a few moments, as
    // evidence of what the face was doing. Nothing else is captured.
    if (bTakeShots && ShotsTaken < 4 && Now - FixtureStartedAt >= 1.5 + 2.5 * ShotsTaken)
    {
        FScreenshotRequest::RequestScreenshot(
            FPaths::ProjectSavedDir() / FString::Printf(TEXT("Screenshots/probe_%d.png"), ShotsTaken), false, false);
        ++ShotsTaken;
    }
    if (Now - FixtureStartedAt > FixtureSeconds + TailSeconds) Report(true);
    else if (Now - LastReportAt >= 2.0) { LastReportAt = Now; Report(false); }
}

void UFreyaAudioProbeComponent::Report(bool bFinal)
{
    const int32 Frames = GetSolverFrameCount();
    if (!bFinal)
    {
        UE_LOG(LogFreyaProbe, Display, TEXT("Progress: %.1f s, solver frames %d, peak curve %.3f over %d curves."),
            FPlatformTime::Seconds() - FixtureStartedAt, Frames, PeakCurve, CurvesAtPeak);
        return;
    }
    bFixtureActive = false;
    // One line that can be searched for in the log of an Editor or a packaged run.
    const TCHAR* Verdict = Frames > 0 && PeakCurve > 0.05f ? TEXT("SOLVER PRODUCED ANIMATION")
        : Frames > 0 ? TEXT("SOLVER RAN BUT CURVES STAYED NEAR ZERO") : TEXT("NO SOLVER OUTPUT");
    UE_LOG(LogFreyaProbe, Display, TEXT("RESULT: %s. solver frames %d, peak curve %.3f over %d curves, fixture %.2f s."),
        Verdict, Frames, PeakCurve, CurvesAtPeak, FixtureSeconds);
    // With -FreyaQuit an unattended test run ends by itself once it has its result.
    if (FParse::Param(FCommandLine::Get(), TEXT("FreyaQuit")) && GetWorld())
    {
        FTimerHandle Unused;
        GetWorld()->GetTimerManager().SetTimer(Unused, FTimerDelegate::CreateWeakLambda(this, [this]()
        {
            UKismetSystemLibrary::QuitGame(this, nullptr, EQuitPreference::Quit, false);
        }), 1.5f, false);
    }
}

void UFreyaAudioProbeComponent::StopProbe()
{
    CancelSpeech();
    if (SourceId.IsValid() && IModularFeatures::Get().IsModularFeatureAvailable(ILiveLinkClient::ModularFeatureName))
        IModularFeatures::Get().GetModularFeature<ILiveLinkClient>(ILiveLinkClient::ModularFeatureName).RemoveSource(SourceId);
    Source.Reset();
    SourceId.Invalidate();
}

void UFreyaAudioProbeComponent::EndPlay(const EEndPlayReason::Type Reason)
{
    if (Link.IsValid()) { Link->Stop(); Link.Reset(); }
    StopProbe();
    Super::EndPlay(Reason);
}
