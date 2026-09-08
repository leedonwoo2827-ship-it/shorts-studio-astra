# 쇼츠공방 II (Shorts Studio II)

**단행본 한 장(章)을 넣으면 9:16 30초 모션 쇼츠가 나옵니다.**

장면 그림이 실제로 움직입니다 — HTML/CSS/GSAP 을 헤드리스 Chrome 이 **프레임을
한 칸씩 seek 하며** 캡처해 굽기 때문에, 실시간 재생이 아니라 **결정론적**입니다.
같은 입력이면 같은 mp4 가 나옵니다.

> **API 키를 쓰지 않습니다.** 구독 로그인 두 개만 씁니다 —
> 대본은 **Claude Code**, 그림은 **ChatGPT**. 환경변수에 남은 키는 무력화합니다.

```
1장.pdf
   ↓ 재료      쪽번호·머리글을 걷어낸 source.md    (사람이 고칠 수 있다)
   ↓ 대본      $ 씬 분할 · 후크 · 자막 · 해시태그
   ↓ 발음      「1840년」 → 「천팔백사십 년」
   ↓ 음성      실측 길이가 씬 길이를 정한다
   ↓ 자막      SRT + 큐
   ↓ 그림지시  $ 세로 판 나누기 · 글자 금지
   ↓ 그림      $ 씬마다 한 장
   ↓ 컴포지션  타이밍 계산 + 렌더할 HTML
   ↓ 빌드      1080×1920 · 30fps · mp4
   ────────────
     결과      $ 유튜브 제목·설명·태그·고정댓글
```

`$` 가 붙은 넷만 크레딧을 씁니다. 나머지는 공짜입니다.

---

## 화면

```
1080 × 1920 · 30fps

y     0~ 300   위 띠     아이보리. 후크 2줄 (1줄 잉크 / 2줄 주황) + 진행 레일
y   300~1620   그림칸    2:3 그림을 폭에 맞춰. 켄번스 + SVG 강조가 그려진다
y  1620~1920   아래 띠   아이보리. 음성 자막 + 해시태그
```

**그림에는 글자가 없습니다.** 글자는 전부 화면 위에 얹는 층입니다. 그래서
오타 수정·모션·다국어가 전부 공짜입니다 — 그림에 글자를 구우면 고칠 수도,
움직일 수도 없습니다.

그림은 2:3 이고 화면은 9:16 입니다. 폭을 맞추면 위아래가 남는데 **남는 자리도
같은 아이보리라 안 보입니다.** 그래서 비율을 늘리거나 좌우를 자르지 않습니다.

---

## 0. 준비물

| | 없으면 | 받는 곳 |
|---|---|---|
| **Python 3.10+** | 안 돕니다 | [python.org](https://www.python.org/downloads/) — *Add Python to PATH* 체크 |
| **Node.js 22+** | 렌더가 안 됩니다 | [nodejs.org](https://nodejs.org/) |
| **ffmpeg** | 음성 변환·자막 얹기가 안 됩니다 | `winget install Gyan.FFmpeg` |
| **Claude Code 로그인** | 대본·그림지시가 안 됩니다 | 터미널에서 `claude` 한 번 |
| **Codex CLI 로그인** | 그림이 안 나옵니다 | `codex login` |

`ffmpeg` 를 깐 뒤에는 **새 터미널**을 열어야 PATH 가 잡힙니다.

> **`codex login status` 를 믿지 마세요.** 그것은 파일이 있는지만 봅니다 —
> 토큰이 만료된 상태에서도 「Logged in」이라고 답합니다. 이 앱은 만료 시각을
> 직접 읽어 좌측 레일 아래에 알려 줍니다.

---

## 1. 설치

```bat
git clone <이 저장소>
cd 260908-youtubeshort-astra

setup.bat     :: 준비물 확인 + venv + 의존성 + Node 패키지
run.bat       :: 메뉴 → W 를 누르면 브라우저가 열립니다
```

`setup.bat` 은 **이 폴더 밖에 아무것도 쓰지 않습니다.** 산출물도 레포 안
`projects/` 에 쌓입니다 — 노트북에 폴더째로 옮기면 작업물까지 같이 갑니다.

---

## 2. 쓰기

### 배치 파일 셋

| | 무엇 |
|---|---|
| `setup.bat` | 처음 한 번. 준비물 확인과 설치 |
| `run.bat` | 내 PC에서 — **전부 됩니다.** 127.0.0.1 전용 |
| `lan-run.bat` | 사내 다른 자리에서 — **보기만 됩니다** (읽기 모드) |

`lan-run.bat` 이 읽기 전용인 것은 **협상 대상이 아닙니다.** 만드는 단계는 이 PC
주인의 구독으로 돕니다. 남의 요청을 내 구독으로 대신 돌리는 것은 약관이 금지하고,
그래서 서버가 루프백이 아닌 곳에서 온 쓰기 요청을 **서버 쪽에서** 거부합니다 —
버튼을 숨기는 것이 아니라 403 을 냅니다.

### 화면 — 왼쪽 레일이 파이프라인입니다

맨 위 **전부 만들기**가 기본이고, 단계별로 들어가는 것은 주로 **발음과 자막을
손보려고**입니다. 단계 줄마다 `$`(크레딧 씀)와 상태점(● 됨 / ● 부분 / ○ 안 됨)이
붙습니다. 산출물이 입력보다 낡으면 점에 붉은 테가 생깁니다.

기록은 **바닥 도크**에 뜹니다. 화면을 옮겨도 살아 있고, 브라우저를 새로 고쳐도
이어집니다. `Ctrl+B` 레일 접기 · `Ctrl+J` 도크 접기.

### 크레딧을 아끼면서 시험하기

그림 한 장이 이 파이프라인에서 가장 비싼 조각입니다. 그래서:

```bat
run.bat  →  6  (Fill placeholder artwork)
```

씬마다 **진짜 그림과 같은 규격**(2:3, 위아래 15% 비움)의 아이보리 자리표시를
만듭니다. 이걸로 컴포지션과 빌드를 끝까지 돌려 볼 수 있습니다. 화면에서도
「자리표시로 채우기 (무료)」 버튼으로 됩니다.

### 창 없이

```bat
.venv-app\Scripts\python scripts\make.py new  "1장.pdf" --title "편지와 전파가 만든 교실" --cuts 3
.venv-app\Scripts\python scripts\make.py all  260908-편지와-전파가-만든-교실
.venv-app\Scripts\python scripts\make.py run  <slug> tts --only 2
.venv-app\Scripts\python scripts\make.py state <slug>
```

화면과 **같은 코드**를 부릅니다(`pipeline/runner.py`).

---

## 3. 설정

`config.json` 이 기본값이고, `config.local.json` 이 이 PC 것입니다(gitignore).
`config.json` 은 손대지 마세요 — 갈아타면 충돌합니다.

| 항목 | 뜻 |
|---|---|
| `shorts.cuts` | 씬 개수. `1` 이면 한 장면 30초, 기본 `3`, 상한 `8` |
| `shorts.seconds` | 목표 길이. 기본 30 |
| `narration.chars_per_sec` | **엔진마다 다른 실측치.** 아래 참고 |
| `narration.speed` | 배속. 쇼츠는 1.2 가 기준 |
| `compose.band_top/bottom` | 위/아래 띠 높이(px) |
| `image.size` | 그림 규격. 세로는 `1024x1536` |
| `image.style_hint` / `negative` | 화풍과 금지 목록 |
| `tts.engine` | `edge`(기본·무료) · `voicewright`(Supertonic) · `none` |

### 낭독 속도를 다시 재는 법 — 엔진을 바꿨다면 필수

`chars_per_sec` 는 **글자 예산의 뿌리**입니다. 틀리면 30초짜리가 24초나 36초로
나옵니다. 실측값이라 엔진·목소리를 바꾸면 다시 재야 합니다.

```
한 편을 굽고 → 「음성」 로그의 합계 초를 본다
cps = (자막 글자 수 합) / (합계 초 × speed)
```

지금 값은 **edge / ko-KR-SunHiNeural 에서 재 것**입니다 —
184자 → 23.54초(1.2배속) → `6.51`. 참고로 Supertonic F2 는 `5.53` 이었습니다.
`config.json` 의 `narration._실측` 메모에 남겨 두었습니다.

### 화풍을 바꿀 때는 공짜로 다시 조립됩니다

`image.style_hint` 를 고친 뒤:

```bat
.venv-app\Scripts\python -c "import sys;sys.path.insert(0,'.');from pipeline import s5_imgprompt as m;print(m.rebuild('<slug>'))"
```

모델을 부르지 않고 지시문 문장만 다시 조립합니다. 모델이 쓴 세 조각
(`scene_line`·`composition`·`palette_note`)은 파일에 남아 있으니까요.
(그림 자체는 지시문이 바뀌었으니 다시 받아야 합니다.)

---

## 4. 폴더

```
projects/<slug>/                slug = YYMMDD-제목
  00_기획/     원본.pdf · source.md · source.json   ← 사람이 넣는 것은 여기뿐
  01_대본/     script.json ★ · 발음교정표.txt
  02_음성/     001.wav …        (실측 길이가 씬 길이를 정한다)
  03_자막/     <slug>.srt · cue-sheet.csv
  04_이미지/   이미지프롬프트.json · 001.png …
  05_컴포지션/ index.html · assets/ · vendor/
  06_완성/     v01_0908-1530/<slug>.mp4 · 유튜브.txt · 대본.txt · 정보.json
               최신.txt   ← 최신 빌드 이름. 빌드는 쌓이고 덮어쓰지 않는다
```

**`04_이미지/` 는 접점입니다.** 그림 단계가 죽어도 `001.png` 처럼 앞 세 자리만
맞춰 넣으면 뒤 단계가 그대로 돕니다. 다른 앱에서 뽑은 그림도, 손으로 그린 것도
됩니다. 자동화는 그 위에 얹은 편의일 뿐입니다.

---

## 5. 인증 두 개를 한 앱에 둔 방식

이 앱은 인증이 둘입니다 — Claude(대본·지시문)와 ChatGPT(그림).
**코드로 잇지 않고 프로세스로 갈랐습니다.**

- 그림 단계는 **별도 서브프로세스**(`scripts/imagegen_bridge.py`)에서 돕니다.
- 각자 자기 것만 읽습니다 — Claude 는 `~/.claude/.credentials.json`,
  그림은 `~/.codex/auth.json`. 서로의 경로를 열지 않습니다.
- Claude 를 부르기 전에 `ANTHROPIC_API_KEY` 계열을, 그림을 부르기 전에
  `OPENAI_API_KEY` 계열을 빈 값으로 덮습니다. 오래된 `export` 가 구독 대신 키로
  나가면 **모르는 사이에 과금**됩니다.
- 그래도 **폴더 접점을 살려 둡니다**(위 4번). 자동화가 죽어도 일이 멈추지 않게.

---

## 6. 안 하는 것

- **업로드를 하지 않습니다.** 올릴 글까지 만들고 멈춥니다. 올리는 순간은
  되돌리기 어렵고 채널 평판이 걸린 자리라 사람이 판단합니다.
- **LAN 에서 만들기를 열지 않습니다** (위 2번).
- **API 키를 쓰지 않습니다.**
- **대본이 예산을 넘어도 자동으로 자르지 않습니다.** 말을 잘라 붙이면 문장이
  깨지고, 깨진 문장은 TTS 에서 더 이상하게 들립니다. 경고만 남기고 사람에게
  넘깁니다.

---

## 7. 막혔을 때

| 증상 | 볼 곳 |
|---|---|
| 그림 단계가 바로 실패 | 좌측 레일 아래 **ChatGPT** 칩. 만료면 `codex login` |
| 대본 단계가 실패 | **Claude** 칩. 안 되면 터미널에서 `claude` 한 번 |
| 렌더 실패 | `run.bat` → `D` (doctor). Chrome·FFmpeg·Node 줄만 보면 됩니다 |
| 30초가 아니라 24초 | `narration.chars_per_sec` 재측정 (위 3번) |
| 후크 글자가 잘림 | 후크 한 줄은 12자까지입니다. 「대본」 화면에서 줄이세요 |
| 자막이 세 줄로 넘침 | `pipeline/s4_subs.py` 의 `CUE_MAX`(26자) |
| 화면은 그대로인데 코드를 고쳤다 | `run.bat` 창을 닫고 다시 (파이썬 변경) |
| 콘솔 한글이 깨짐 | 화면·영상에는 영향 없습니다 (cp949 표시 문제) |

### 다시 밟지 말 것 — 실측으로 배운 것

- **`data-start` 는 숫자만.** id 참조를 쓰면 정적 프레임 dedup 이 꺼져 렌더가
  2배 넘게 느려집니다.
- **자막 큐는 루트 직속.** 씬 clip 안에 넣으면 씬이 사라질 때 같이 사라져
  마지막 큐가 잘립니다.
- **node 에 `CREATE_NO_WINDOW` 를 주지 마세요.** node 가 콘솔을 못 물려받으면
  Chrome 자식마다 새 콘솔이 생깁니다(실측: 검은 창 11개).
- **폰트 서브셋 `--unicodes` 에 `U+AC00-D7A3` 을 넣지 마세요.** 서브셋이 스스로
  무력화돼 6MB 가 그대로 실립니다. 본문 한글은 `--text-file` 이 잡습니다.
- **SRT 사본에는 UTF-8 BOM.** 없으면 cp949 오탐이 「그럴듯하게 깨진 한글」을
  만듭니다 — 알아채기 어려운 종류의 깨짐입니다.
- **GSAP `drawSVG` 를 쓰지 마세요.** 유료 Club 플러그인이라 무료 빌드에 없고,
  없으면 **조용히 아무 일도 안 일어납니다.** dash 로 긋습니다.

---

## 의존

ffmpeg · FastAPI · uvicorn · Jinja2 · edge-tts · fontTools ·
[HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0) ·
GSAP (무료 빌드, 자체 호스팅) ·
[Pretendard](https://github.com/orioncactus/pretendard) · Black Han Sans (OFL)
