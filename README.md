# APPA (Audio Production Pipeline Agent)

APPA는 여러 핀 마이크로 수음된 방송 오디오에서 발화 후보 구간을 탐색하고, 원본 트랙의 enable/disable 판단을 실험하는 로컬 프로토타입입니다. 현재 웹 앱은 멀티트랙 재생, RMS 기반 activity 분석, gate smoothing, fade, 구간 편집과 선택 구간 BSS 분석을 지원합니다.

이 저장소에는 저작권 및 개인정보 보호를 위해 원본 WAV, 프록시 오디오, Pro Tools 세션, BSS 결과와 분석 캐시를 포함하지 않습니다.

## 주요 기능

- 복수 오디오 트랙 동기 재생 및 waveform 탐색
- 20분 단위 타임라인 이동, zoom, seek, selection
- 트랙별 RMS activity score와 상대 dominance 기반 발화 후보 검출
- threshold, off-gap fill, minimum-on duration, RMS gate 조정
- enable/disable 전환 구간의 fade-in/fade-out 미리듣기
- 선택 구간 CPU BSS(AuxIVA, ILRMA, FastMNMF) 분석 및 캐시
- segment JSON 내보내기

## 실행 환경

- Python 3.11 이상
- FFmpeg 및 FFprobe
- 최신 Chrome 또는 Chromium 계열 브라우저

macOS에서는 다음과 같이 준비할 수 있습니다.

```bash
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 실행

프로젝트 루트에서 서버를 시작합니다.

```bash
python scripts/serve_web.py --host 127.0.0.1 --port 5177
```

브라우저에서 `http://localhost:5177`을 엽니다. 같은 네트워크의 다른 기기에서 접근하려면 `--host 0.0.0.0`으로 실행하고, Mac의 로컬 IP와 포트 `5177`로 접속합니다.

## 오디오 데이터 준비

브라우저의 **Load Files**에서 복수 오디오 파일을 선택할 수 있습니다. 작은 파일은 브라우저에서 직접 분석합니다.

현재 대용량 WAV의 서버 프록시 생성 흐름은 프로젝트 루트의 `미우새/` 폴더에서 다음 이름을 포함하는 4개 파일을 찾습니다.

```text
서장훈_02.wav
박중훈_02.wav
신동엽_02.wav
희철맘_02.wav
```

이 폴더와 내부 데이터는 `.gitignore` 대상입니다. 대용량 파일을 선택하기 전에 로컬에서만 해당 폴더를 준비해야 합니다. 생성되는 MP3 프록시, waveform JSON, RMS/BSS 분석 결과는 `web/assets/`에 저장되며 Git에는 포함되지 않습니다.

## 단일 WAV RMS 분석

전체 WAV를 8kHz mono 스트림으로 디코딩하면서 200ms window, 100ms hop으로 RMS를 계산할 수 있습니다.

```bash
python scripts/analyze_single_wav_rms.py /absolute/path/to/input.wav \
  --output-dir analysis_outputs/rms/example
```

요약 JSON, 프레임/분 단위 CSV, 압축 NPZ와 RMS 분포 PNG가 생성됩니다. `analysis_outputs/`는 재생성 가능한 산출물이므로 Git에서 제외됩니다.

## 프로젝트 구조

```text
web/         브라우저 UI
scripts/     프록시, waveform, RMS, BSS 분석 및 로컬 서버
```

## 현재 범위

APPA는 방송 납품용 완성 제품이 아니라 오디오 gate 판단과 에이전트 연동 가능성을 검증하기 위한 실험용 도구입니다. 자동 판단 결과는 원본을 훼손하지 않으며, 실제 편집 및 납품 전에는 오디오 감독의 청취 검수가 필요합니다.
