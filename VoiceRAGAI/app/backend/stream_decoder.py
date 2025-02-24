import os
import wave
import base64

# Define constants for audio format
SAMPLE_RATE = 24000  # 16 kHz sample rate (adjust based on your actual sample rate)
NUM_CHANNELS = 1  # Mono audio (adjust if stereo)
SAMPLE_WIDTH = 2  # 2 bytes for 16-bit PCM audio
CHUNK_SIZE = 1024  # Adjust the chunk size as needed

def decode_base64_to_pcm(base64_chunks, output_pcm_file):
    """
    Decodes a list of base64 audio chunks and saves them as a PCM file.
    """
    combined_audio = b"".join(base64.b64decode(chunk) for chunk in base64_chunks)
    
    # Write the combined PCM data to a file
    with open(output_pcm_file, "wb") as pcm_file:
        pcm_file.write(combined_audio)
    print(f"PCM audio saved to {output_pcm_file}")


def pcm_to_wav(pcm_filename, wav_filename, sample_rate=16000):
    """
    Converts a raw PCM file to a WAV file.
    """
    with open(pcm_filename, 'rb') as pcm_file:
        pcm_data = pcm_file.read()
    
    with wave.open(wav_filename, 'wb') as wav_file:
        wav_file.setnchannels(NUM_CHANNELS)  # Mono
        wav_file.setsampwidth(SAMPLE_WIDTH)  # PCM16 has 2 bytes per sample
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_data)
    
    print(f"WAV file saved to {wav_filename}")

# Function to read the log file and process the chunks
def process_audio_log(input_log_file):
    pcm_data = []
    
    with open(input_log_file, 'r') as log_file:
        for line in log_file:
            # Ignore empty lines
            if line.strip() == '':
                continue
            
            # Assuming the line contains raw PCM data (in hexadecimal, base64, or raw binary format)
            # Convert the line to bytes (this assumes that the log contains binary data as a string)
            try:
                chunk = line.strip()  
                # print(chunk)
                pcm_data.append(chunk)
            except Exception as e:
                print(f"Error processing line: {line}")
                print(e)

    return pcm_data

# Main function to process the log and generate PCM/WAV files
def main(configuration: str):
    current_path = os.path.dirname(os.path.abspath(__file__))  # Get the current script directory
    print(f"Current path: {current_path}")

    input_log_file =  os.path.join(current_path, 'logs', f'{configuration}_audio.log')
    
    # Define output file paths using current_path to ensure they're located relative to the script
    output_pcm_file = os.path.join(current_path, 'audio', f'{configuration}_audio.pcm')
    output_wav_file = os.path.join(current_path, 'audio', f'{configuration}_audio.wav')
    
    # Read the audio log file and get the PCM data
    pcm_buffer = process_audio_log(input_log_file)
    
    # Write to PCM file
    decode_base64_to_pcm(pcm_buffer, output_pcm_file)
    
    # Write to WAV file
    pcm_to_wav(output_pcm_file, output_wav_file, SAMPLE_RATE)
    

if __name__ == '__main__':
    configs = ['acs', 'openai']
    # adjust the configuration based on the log file you want to process
    print("1: acs")
    print("2: openai")
    user_choice = input("Enter your choice (1 or 2): ")
    configuration = configs[int(user_choice) - 1]
    main(configuration)
