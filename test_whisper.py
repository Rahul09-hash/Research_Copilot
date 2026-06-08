import sys
import numpy as np
from transformers import pipeline

try:
    print("Loading pipeline...")
    pipe = pipeline("automatic-speech-recognition", model="openai/whisper-tiny")
    
    print("Generating dummy audio (16kHz)...")
    # 1 second of silence
    dummy_audio = np.zeros(16000, dtype=np.float32)
    
    print("Running inference...")
    res = pipe(dummy_audio)
    print("Result:", res)
    print("SUCCESS")
except Exception as e:
    import traceback
    traceback.print_exc()
