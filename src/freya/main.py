import re

import urllib.request

import threading



from freya.core.assistant import FreyaAssistant

from freya.core.model_runtime import ModelRuntimeUnavailable

from freya.gpu.resource_manager import GPUResourceManager

from freya.image.image_generator import FreyaImageGenerator

from freya.control_plane import build_local_control_plane
from freya.config import OPEN_WINDOW
from freya.hands_free import LISTENING_COMMANDS
from freya.hands_free import describe_listening
from freya.hands_free import handle_listening_command
from freya.hands_free import load_speech_recognition
from freya.hands_free import start_background_listening
from freya.settings import Settings
from freya.turn_gate import TurnGate
from freya.events import EventBus
from freya.image.gallery import ImageGallery
from freya.window import WINDOW_COMMAND
from freya.window import FreyaWindow
from freya.window import WindowActions
from freya.window import build_status
from freya.tools.tool_router import FreyaToolRouter

from freya.voice.stt import FreyaSTT

from freya.voice.tts import FreyaVoice





VOICE_FILE_COMMAND = "/voice-file"

TALK_COMMAND = "/talk"

LISTEN_COMMAND = "/listen"

CONVERSATION_COMMAND = "/conversation"

INTERRUPT_COMMAND = "/interrupt"

IMAGE_COMMAND = "/image"

COMMANDS = (

    VOICE_FILE_COMMAND,

    TALK_COMMAND,

    LISTEN_COMMAND,

    CONVERSATION_COMMAND,

    INTERRUPT_COMMAND,

    IMAGE_COMMAND,

) + LISTENING_COMMANDS + (WINDOW_COMMAND,)



# Everything that happens in a conversation is announced here, so the

# window can show it. The console keeps printing as before.

EVENTS = EventBus()

# Freya's own copies of generated images; set up in main().

GALLERY = None





def normalize_command(user_input):

    """

    Accept a command typed with a backslash, such as \\listen.

    Anything that is not a known command is returned unchanged.

    """

    if not user_input.startswith("\\"):

        return user_input

    words = user_input[1:].split(maxsplit=1)

    if not words:

        return user_input

    command = "/" + words[0].lower()

    if command not in COMMANDS:

        return user_input

    return "/" + user_input[1:]





def extract_complete_sentences(buffer):

    sentences = []

    sentence_end = re.compile(

        r"(.+?[.!?]+)(?:\s+|$)",

        re.DOTALL,

    )



    while True:

        match = sentence_end.match(buffer)



        if match is None:

            break



        sentence = match.group(1).strip()



        if sentence:

            sentences.append(sentence)



        buffer = buffer[

            match.end():

        ]



    return sentences, buffer





def stream_freya_response(

    freya,

    voice,

    user_input,

):

    print(

        "\nFreya: ",

        end="",

        flush=True,

    )

    EVENTS.publish("assistant_start")



    speech_buffer = ""



    for chunk in freya.respond_stream(

        user_input

    ):

        print(

            chunk,

            end="",

            flush=True,

        )

        EVENTS.publish(

            "assistant_chunk",

            text=chunk,

        )



        speech_buffer += chunk



        sentences, speech_buffer = (

            extract_complete_sentences(

                speech_buffer

            )

        )



        for sentence in sentences:

            voice.speak(

                sentence

            )



    remaining_text = (

        speech_buffer.strip()

    )



    if remaining_text:

        voice.speak(

            remaining_text

        )

    EVENTS.publish("assistant_end")



    print("\n")





def get_voice_file_path(command):

    path = command[

        len(VOICE_FILE_COMMAND):

    ].strip()



    return path.strip('"')





def get_image_prompt(command):

    return command[

        len(IMAGE_COMMAND):

    ].strip()





def announce_image_failure(exc):

    EVENTS.publish("image_failed")

    EVENTS.publish(

        "notice",

        text=f"Image generation failed. {exc}",

    )




def keep_generated_image(prompt, result):

    """

    Copy a finished image into Freya's gallery and announce it.

    """

    if GALLERY is None or not result["image_urls"]:

        EVENTS.publish("image_failed")

        return


    try:

        with urllib.request.urlopen(

            result["image_urls"][0],

            timeout=30,

        ) as response:

            image = GALLERY.add(

                prompt,

                response.read(),

                seed=result.get("seed"),

            )

    except (OSError, ValueError) as exc:

        announce_image_failure(exc)

        return


    EVENTS.publish(

        "image_ready",

        image=image,

    )




def run_image_generation(

    image_generator,

    gpu_manager,

    prompt,

):

    if not prompt:

        print(

            "\nUsage: /image <description>\n"

        )

        return



    print()

    try:

        # Start ComfyUI first if it is not running, so the language

        # model is not unloaded for an image that cannot be made.

        image_generator.ensure_running()

    except RuntimeError as exc:

        print(

            f"Freya: I can't generate images right now. {exc}\n"

        )

        EVENTS.publish(

            "notice",

            text=f"I can't generate images right now. {exc}",

        )

        return



    print("Freya: Preparing GPU for image generation...")

    EVENTS.publish(

        "image_started",

        prompt=prompt,

    )

    print(f"Prompt: {prompt}")

    print()



    try:

        # Release Ollama's LLM and embedding models before

        # ComfyUI loads the much larger image model.

        gpu_manager.unload_all_ollama_models()



    except Exception as exc:

        print(

            "Freya: Could not release Ollama GPU resources."

        )

        print(

            f"Error: {exc}\n"

        )

        announce_image_failure(exc)

        return



    print(

        "Freya: GPU ready. Generating image..."

    )

    print()



    try:

        result = image_generator.generate(

            prompt

        )



    except Exception as exc:

        print(

            "Freya: Image generation failed."

        )

        print(

            f"Error: {exc}\n"

        )

        announce_image_failure(exc)

        return



    finally:

        # Whether generation succeeds or fails, ask ComfyUI

        # to release its models so the GPU is available for

        # Freya's next LLM request.

        try:

            gpu_manager.free_comfyui_memory()



        except Exception as exc:

            print(

                "GPU Manager warning: "

                "ComfyUI memory cleanup failed."

            )

            print(

                f"Cleanup error: {exc}"

            )



    print(

        "Freya: Image generated successfully."

    )

    keep_generated_image(

        prompt,

        result,

    )

    print(

        f"Seed: {result['seed']}"

    )



    for image in result["images"]:

        filename = image.get(

            "filename",

            "Unknown",

        )



        subfolder = image.get(

            "subfolder",

            "",

        )



        image_type = image.get(

            "type",

            "output",

        )



        print(

            f"Output: {filename}"

        )



        if subfolder:

            print(

                f"Subfolder: {subfolder}"

            )



        print(

            f"Type: {image_type}"

        )



    for url in result["image_urls"]:

        print(

            f"Image URL: {url}"

        )



    print()





def handle_tool_request(
    tool_router,
    image_generator,
    gpu_manager,
    user_input,
):
    tool_request = tool_router.route(
        user_input
    )

    if tool_request is None:
        return False

    if tool_request.tool == "image":
        run_image_generation(
            image_generator,
            gpu_manager,
            tool_request.prompt,
        )
        return True

    return False


def handle_normal_input(

    freya,

    voice,

    tool_router,

    image_generator,

    gpu_manager,

    user_input,

    source="typed",

):

    EVENTS.publish(

        "user",

        text=user_input,

        source=source,

    )

    tool_was_used = handle_tool_request(

        tool_router,

        image_generator,

        gpu_manager,

        user_input,

    )



    if tool_was_used:

        return



    try:

        stream_freya_response(

            freya,

            voice,

            user_input,

        )

    except ModelRuntimeUnavailable as exc:

        print(

            f"\n\nFreya: {exc}\n"

        )

        EVENTS.publish("assistant_end")

        EVENTS.publish(

            "notice",

            text=str(exc),

        )





def run_conversation_mode(

    freya,

    voice,

    stt,

    tool_router,

    image_generator,

    gpu_manager,

):

    print()

    print("Conversation mode started.")

    print(

        "Say 'Freya stop conversation' "

        "to return to keyboard mode."

    )

    print(

        "If no speech is detected for 10 seconds, "

        "conversation mode will also end."

    )



    while True:

        try:

            audio_path = stt.record_until_silence(

                wait_for_enter=False

            )



            transcript, info = stt.transcribe(

                audio_path

            )



        except RuntimeError as exc:

            if "No speech was detected" in str(exc):

                print(

                    "\nNo speech detected. "

                    "Leaving conversation mode.\n"

                )

                return



            raise



        transcript = transcript.strip()



        if not transcript:

            print(

                "\nNo speech was detected "

                "in that recording.\n"

            )

            continue



        print()

        print(

            "You (voice): "

            f"{transcript}"

        )

        print(

            "Detected language: "

            f"{info.language}"

        )



        normalized = (

            transcript.lower()

            .strip()

            .rstrip(".!?")

        )



        if normalized in {

            "freya stop conversation",

            "freya stop listening",

            "stop conversation",

            "exit conversation",

        }:

            print(

                "\nFreya: Conversation mode ended.\n"

            )

            voice.speak(

                "Conversation mode ended."

            )

            voice.wait_until_done()

            return



        handle_normal_input(

            freya,

            voice,

            tool_router,

            image_generator,

            gpu_manager,

            transcript,

            source="voice",

        )



        # Important for v1: do not reopen the microphone

        # until Freya has finished speaking. This prevents

        # her own TTS audio from being treated as user speech.

        voice.wait_until_done()





def main():

    global GALLERY

    control_plane = build_local_control_plane()

    for message in control_plane.startup_messages():

        print(message)

    # Load the Ollama models while the voice engine is starting up.

    threading.Thread(

        target=control_plane.warm_models,

        name="FreyaModelWarmup",

        daemon=True,

    ).start()



    freya = FreyaAssistant(

        tool_host=control_plane.model_tools,

    )

    voice = FreyaVoice()

    stt = load_speech_recognition()

    settings = Settings()

    gate = TurnGate()

    GALLERY = ImageGallery()



    def announce_image_backend(message):

        print(message)

        EVENTS.publish(

            "notice",

            text=message.removeprefix("Freya: "),

        )


    image_generator = FreyaImageGenerator(

        ensure_running=lambda: control_plane.ensure_image_backend(

            announce=announce_image_backend,

        ),

    )

    tool_router = FreyaToolRouter()

    gpu_manager = GPUResourceManager()



    print("Freya online.")

    print("Voice: enabled")

    print("Streaming: enabled")

    print("Async voice: enabled")

    print("Voice-file input: enabled")

    print("Push-to-talk: enabled")

    print("Automatic silence detection: enabled")

    print("Conversation mode: enabled")

    print("Interruptible TTS: enabled")

    print("Image generation: enabled")

    print("Natural-language tool routing: enabled")

    print("Tool registry: enabled")

    print("System tools: enabled")

    print("GPU resource manager: enabled")

    print()

    print("Use /talk for manual push-to-talk.")

    print("Use /listen for automatic silence detection.")

    print("Use /conversation for hands-free conversation.")

    print("Use /interrupt to stop current speech playback.")

    print(

        "Use /voice-file <path> "

        "to transcribe an audio file."

    )

    print(

        "Use /image <description> "

        "to generate an image."

    )

    print(

        "Or ask Freya naturally to "

        "create an image."

    )

    print("Use /names to see the names Freya answers to.")

    print("Use /window to open Freya's window.")

    print("Type 'exit' to quit.\n")



    def handle_spoken_request(request):

        # Runs on the listener thread while the keyboard waits.

        with gate.spoken_turn() as acquired:

            if not acquired:

                return

            if not request:

                print("\rYou (voice): Freya\n\nFreya: Yes?\n")

                voice.speak("Yes?")

            else:

                print(f"\rYou (voice): {request}")

                handle_normal_input(

                    freya,

                    voice,

                    tool_router,

                    image_generator,

                    gpu_manager,

                    request,

                    source="voice",

                )

            print("You: ", end="", flush=True)



    listener = start_background_listening(

        stt,

        voice,

        gate,

        settings,

        handle_spoken_request,

    )

    print(describe_listening(listener, settings))



    def current_status():

        return build_status(

            listener,

            settings,

            control_plane,

        )


    def publish_status():

        EVENTS.publish(

            "status",

            status=current_status(),

        )


    def say_from_window(text):

        # Runs on the window's worker thread; waits for any turn

        # already in progress.

        with gate.turn():

            print(f"\rYou (window): {text}")

            handle_normal_input(

                freya,

                voice,

                tool_router,

                image_generator,

                gpu_manager,

                text,

                source="window",

            )

            publish_status()

            print("You: ", end="", flush=True)


    def image_from_window(prompt):

        with gate.turn():

            print(f"\rYou (window): /image {prompt}")

            EVENTS.publish(

                "user",

                text=f"Generate an image: {prompt}",

                source="window",

            )

            run_image_generation(

                image_generator,

                gpu_manager,

                prompt,

            )

            publish_status()

            print("You: ", end="", flush=True)


    def mute_from_window(muted):

        if listener is not None and listener.running:

            if muted:

                listener.mute()

            else:

                listener.unmute()

        publish_status()


    window = FreyaWindow(

        EVENTS,

        GALLERY,

        WindowActions(

            say=say_from_window,

            generate_image=image_from_window,

            set_muted=mute_from_window,

            interrupt=voice.interrupt,

            status=current_status,

        ),

    )

    if window.start():

        if OPEN_WINDOW:

            print(window.open())

        else:

            print("Use /window to open Freya's window.")

    print()



    try:

        while True:

            user_input = normalize_command(

                gate.read_line(

                    "You: "

                ).strip()

            )



            if user_input.lower() in {

                "exit",

                "quit",

            }:

                print("Freya: Goodbye.")

                voice.speak("Goodbye.")

                voice.wait_until_done()

                break



            if not user_input:

                continue



            if user_input.lower() == INTERRUPT_COMMAND:

                voice.interrupt()

                print(

                    "\nFreya: Speech playback interrupted.\n"

                )

                continue



            if handle_listening_command(

                user_input,

                listener,

                settings,

            ):

                publish_status()

                continue


            if user_input.lower() == WINDOW_COMMAND:

                print(f"\n{window.open()}\n")

                continue



            if user_input.lower() == IMAGE_COMMAND:

                print(

                    "\nUsage: /image <description>\n"

                )

                continue



            if user_input.lower().startswith(

                IMAGE_COMMAND + " "

            ):

                prompt = get_image_prompt(

                    user_input

                )



                run_image_generation(

                    image_generator,

                    gpu_manager,

                    prompt,

                )



                continue



            if user_input.lower() == CONVERSATION_COMMAND:

                try:

                    if stt is None:

                        stt = FreyaSTT()



                    run_conversation_mode(

                        freya,

                        voice,

                        stt,

                        tool_router,

                        image_generator,

                        gpu_manager,

                    )



                except Exception as exc:

                    print(

                        "\nConversation mode error: "

                        f"{exc}\n"

                    )



                continue



            if user_input.lower() == LISTEN_COMMAND:

                try:

                    if stt is None:

                        stt = FreyaSTT()



                    audio_path = (

                        stt.record_until_silence()

                    )



                    transcript, info = stt.transcribe(

                        audio_path

                    )



                except Exception as exc:

                    print(

                        "\nAutomatic listening error: "

                        f"{exc}\n"

                    )

                    continue



                transcript = transcript.strip()



                if not transcript:

                    print(

                        "\nNo speech was "

                        "detected from the microphone.\n"

                    )

                    continue



                print()

                print(

                    "You (voice): "

                    f"{transcript}"

                )

                print(

                    "Detected language: "

                    f"{info.language}"

                )



                handle_normal_input(

                    freya,

                    voice,

                    tool_router,

                    image_generator,

                    gpu_manager,

                    transcript,

                    source="voice",

                )



                continue



            if user_input.lower() == TALK_COMMAND:

                try:

                    if stt is None:

                        stt = FreyaSTT()



                    audio_path = stt.record_push_to_talk()



                    transcript, info = stt.transcribe(

                        audio_path

                    )



                except Exception as exc:

                    print(

                        "\nMicrophone error: "

                        f"{exc}\n"

                    )

                    continue



                transcript = transcript.strip()



                if not transcript:

                    print(

                        "\nNo speech was "

                        "detected from the microphone.\n"

                    )

                    continue



                print()

                print(

                    "You (voice): "

                    f"{transcript}"

                )

                print(

                    "Detected language: "

                    f"{info.language}"

                )



                handle_normal_input(

                    freya,

                    voice,

                    tool_router,

                    image_generator,

                    gpu_manager,

                    transcript,

                    source="voice",

                )



                continue



            if user_input.lower().startswith(

                VOICE_FILE_COMMAND

            ):

                audio_path = get_voice_file_path(

                    user_input

                )



                if not audio_path:

                    print(

                        "\nUsage: "

                        "/voice-file "

                        "<audio file path>\n"

                    )

                    continue



                try:

                    if stt is None:

                        stt = FreyaSTT()



                    transcript, info = (

                        stt.transcribe(

                            audio_path

                        )

                    )



                except Exception as exc:

                    print(

                        "\nVoice-file error: "

                        f"{exc}\n"

                    )

                    continue



                transcript = transcript.strip()



                if not transcript:

                    print(

                        "\nNo speech was "

                        "detected in that "

                        "audio file.\n"

                    )

                    continue



                print()

                print(

                    "You (voice): "

                    f"{transcript}"

                )

                print(

                    "Detected language: "

                    f"{info.language}"

                )



                handle_normal_input(

                    freya,

                    voice,

                    tool_router,

                    image_generator,

                    gpu_manager,

                    transcript,

                    source="voice",

                )



                continue



            handle_normal_input(

                freya,

                voice,

                tool_router,

                image_generator,

                gpu_manager,

                user_input,

            )



    except KeyboardInterrupt:

        print(

            "\nFreya: Shutting down."

        )



    finally:

        if listener is not None:

            listener.stop()

        gate.close()

        window.stop()

        voice.shutdown()

        control_plane.close()





if __name__ == "__main__":

    main()