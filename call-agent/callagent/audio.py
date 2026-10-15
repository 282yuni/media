"""통화 오디오 입출력.

상대방 목소리: 휴대폰 연결 앱의 스피커 → 가상 케이블 → (call_input) → 이 프로그램
AI 목소리:     이 프로그램 → (ai_output) → 가상 케이블 → 휴대폰 연결 앱의 마이크
"""
import queue
import threading
import time

import numpy as np
import sounddevice as sd


def list_devices() -> None:
    for i, d in enumerate(sd.query_devices()):
        kinds = []
        if d["max_input_channels"] > 0:
            kinds.append("입력")
        if d["max_output_channels"] > 0:
            kinds.append("출력")
        api = sd.query_hostapis(d["hostapi"])["name"]
        print(f"[{i:2}] {'/'.join(kinds):5} {d['name']}  ({api}, {int(d['default_samplerate'])}Hz)")


def find_device(name: str, kind: str) -> int | None:
    """장치 이름 일부로 찾기. kind = 'input' | 'output'. 빈 이름이면 None."""
    if not name:
        return None
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d[key] > 0:
            return i
    raise RuntimeError(f"오디오 장치를 못 찾았습니다: '{name}' ({kind}). `python main.py devices` 로 이름을 확인하세요.")


def rms(block: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(block.astype(np.float32) / 32768.0)))) if len(block) else 0.0


class Listener:
    """상대방 음성을 계속 받아서, 말 한 덩어리(발화)씩 잘라 준다."""

    BLOCK_SEC = 0.03

    def __init__(self, cfg: dict):
        a = cfg["audio"]
        self.rate = a.get("input_rate", 16000)
        self.threshold = a.get("speech_threshold", 0.015)
        self.end_silence = a.get("end_silence_sec", 0.8)
        self.max_sec = a.get("max_utterance_sec", 25)
        self.device = find_device(a["call_input"], "input")
        self.blocks: queue.Queue[np.ndarray] = queue.Queue()
        self.is_speaking = threading.Event()  # barge-in 감지용
        self.stream = sd.InputStream(
            samplerate=self.rate, channels=1, dtype="int16", device=self.device,
            blocksize=int(self.rate * self.BLOCK_SEC), callback=self._cb,
        )

    def _cb(self, indata, frames, t, status):
        block = indata[:, 0].copy()
        if rms(block) >= self.threshold:
            self.is_speaking.set()
        self.blocks.put(block)

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()

    def flush(self) -> None:
        while not self.blocks.empty():
            self.blocks.get_nowait()
        self.is_speaking.clear()

    def next_utterance(self, timeout: float | None = None, stop: threading.Event | None = None) -> np.ndarray | None:
        """한 발화가 끝날 때까지 기다렸다가 int16 배열로 돌려준다. timeout 동안 말이 없으면 None."""
        pre_roll: list[np.ndarray] = []      # 말 시작 직전 0.3초도 같이 넣어야 첫 음절이 안 잘림
        speech: list[np.ndarray] = []
        silent_for = voiced = 0.0
        started = None
        waited = 0.0
        while True:
            if stop is not None and stop.is_set():
                return None
            try:
                block = self.blocks.get(timeout=0.2)
            except queue.Empty:
                waited += 0.2
                if started is None and timeout is not None and waited >= timeout:
                    return None
                continue
            dur = len(block) / self.rate
            loud = rms(block) >= self.threshold
            if started is None:
                waited += dur
                pre_roll = (pre_roll + [block])[-10:]
                if loud:
                    started = time.time()
                    speech = pre_roll[:]
                    voiced = dur
                elif timeout is not None and waited >= timeout:
                    return None
                continue
            speech.append(block)
            silent_for = 0.0 if loud else silent_for + dur
            voiced += dur if loud else 0.0
            total = sum(len(b) for b in speech) / self.rate
            if silent_for >= self.end_silence or total >= self.max_sec:
                self.is_speaking.clear()
                audio = np.concatenate(speech)
                # 0.25초도 안 되는 소리(잡음, 기침)는 무시하고 계속 기다림
                if voiced < 0.25:
                    speech, pre_roll, started, silent_for, voiced = [], [], None, 0.0, 0.0
                    continue
                return audio


class Speaker:
    """PCM(int16 mono) 조각을 받아 재생. stop() 하면 즉시 끊긴다 (끼어들기)."""

    def __init__(self, device_name: str, rate: int):
        self.rate = rate
        self.device = find_device(device_name, "output")
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16",
                                      device=self.device, callback=self._cb)
        self.stream.start()

    def _cb(self, outdata, frames, t, status):
        need = frames * 2
        with self.lock:
            chunk = bytes(self.buf[:need])
            del self.buf[:need]
        if len(chunk) < need:
            chunk += b"\x00" * (need - len(chunk))
        outdata[:, 0] = np.frombuffer(chunk, dtype=np.int16)

    def write(self, pcm: bytes) -> None:
        with self.lock:
            self.buf.extend(pcm)

    def stop(self) -> None:
        with self.lock:
            self.buf.clear()

    def pending_sec(self) -> float:
        with self.lock:
            return len(self.buf) / 2 / self.rate

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


class Mouth:
    """AI 목소리를 통화(가상 마이크)와 내 헤드셋(모니터)으로 동시에 내보낸다."""

    def __init__(self, cfg: dict, rate: int):
        a = cfg["audio"]
        self.outs = [Speaker(a["ai_output"], rate)]
        if a.get("monitor_output"):
            self.outs.append(Speaker(a["monitor_output"], rate))
        self.muted = False

    def write(self, pcm: bytes) -> None:
        if not self.muted:
            for o in self.outs:
                o.write(pcm)

    def stop(self) -> None:
        for o in self.outs:
            o.stop()

    def busy(self) -> bool:
        return self.outs[0].pending_sec() > 0.05

    def wait_done(self, interrupt: threading.Event | None = None) -> bool:
        """다 말할 때까지 대기. 중간에 interrupt 가 켜지면 멈추고 False."""
        while self.busy():
            if interrupt is not None and interrupt.is_set():
                self.stop()
                return False
            time.sleep(0.03)
        return True

    def close(self) -> None:
        for o in self.outs:
            o.close()


def meter(cfg: dict, seconds: float = 15) -> None:
    """call_input 볼륨을 실시간으로 보여준다. speech_threshold 정하는 용도."""
    a = cfg["audio"]
    dev = find_device(a["call_input"], "input")
    rate = a.get("input_rate", 16000)
    print(f"{seconds:.0f}초 동안 상대방 소리 크기를 표시합니다. (현재 기준값 {a['speech_threshold']})")
    end = time.time() + seconds

    def cb(indata, frames, t, status):
        level = rms(indata[:, 0])
        bar = "█" * min(60, int(level * 600))
        mark = "◀ 말하는 중" if level >= a["speech_threshold"] else ""
        print(f"\r{level:0.4f} {bar:<60} {mark:<10}", end="", flush=True)

    with sd.InputStream(samplerate=rate, channels=1, dtype="int16", device=dev,
                        blocksize=int(rate * 0.05), callback=cb):
        while time.time() < end:
            time.sleep(0.1)
    print()
