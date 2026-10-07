import re

import threading



from freya.core.assistant import FreyaAssistant

from freya.core.model_runtime import ModelRuntimeUnavailable

from freya.gpu.resource_manager import GPUResourceManager

from freya.image.image_generator import FreyaImageGenerator

from freya.control_plane import build_local_control_plane
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

)





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



    speech_buffer = ""



    for chunk in freya.respond_stream(

        user_input

    ):

        print(

            chunk,

            end="",

            flush=True,

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

    print("Freya: Preparing GPU for image generation...")

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

):

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

        )



        # Important for v1: do not reopen the microphone

        # until Freya has finished speaking. This prevents

        # her own TTS audio from being treated as user speech.

        voice.wait_until_done()





def main():

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

    stt = None



    image_generator = FreyaImageGenerator()

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

    print("Type 'exit' to quit.\n")



    try:

        while True:

            user_input = normalize_command(

                input(

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

        voice.shutdown()

        control_plane.close()





if __name__ == "__main__":

    main()