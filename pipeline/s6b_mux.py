# -*- coding: utf-8 -*-
"""자막 트랙 얹기 — 렌더 뒤 MP4 에 SRT 를 **다시 인코딩하지 않고** 넣는다.

    ffmpeg -i out.mp4 -i ko.srt -i ru.srt -c copy -c:s mov_text …

★ **이것이 다국어의 핵심이다.** 내레이션은 한국어로 한 번만 렌더하고, 자막만
  언어별로 얹는다. 번인하면 언어마다 4분씩 다시 렌더해야 하지만, 트랙이면
  같은 영상에 트랙을 더하는 것으로 끝난다(1초).

    한국어 내레이션 + 러시아어 자막   ← 우즈베키스탄 같은 자리
    한국어 내레이션 + 영어 자막
    …전부 같은 MP4 하나에서 나온다.

★ `-c copy` 다. 영상·소리를 건드리지 않으므로 화질이 그대로다.

★ mov_text 는 MP4 의 표준 자막이고 UTF-8 이라 키릴·한글 다 들어간다.
  못 읽는 플레이어에 보낼 자리에서는 `compose.subtitles: "burn"` 으로 굽는다.

★ **04_자막 폴더에 `<slug>.<lang>.srt` 를 두면 자동으로 함께 얹힌다.**
  예: `260901-…ko.srt` 는 기본, `260901-….ru.srt` 를 옆에 두면 러시아어 트랙이 생긴다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ★ 이 레포에는 번역 단계가 없다(30초 쇼츠에 다국어 자막을 지고 갈 값이 아직 없다).
#   그래서 표를 여기서 든다 — 단 **한 곳에서만** 든다. 나중에 번역 단계를 붙이면
#   그쪽으로 옮기고 여기서는 import 만 한다. 두 벌로 두면 언어를 더할 때 한쪽만
#   고쳐, 만들어 둔 자막이 꼬리표를 못 알아봐 조용히 빠진다.
_LANGS: Dict[str, Dict[str, str]] = {
    "eng": {"tag": "en", "native": "English"},
    "jpn": {"tag": "ja", "native": "日本語"},
    "zho": {"tag": "zh", "native": "中文"},
    "rus": {"tag": "ru", "native": "Русский"},
    "spa": {"tag": "es", "native": "Español"},
    "vie": {"tag": "vi", "native": "Tiếng Việt"},
}

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_BOM = bytes((0xEF, 0xBB, 0xBF))    # UTF-8 BOM

# 파일 이름 꼬리표 → ISO 639-2. `<slug>.ru.srt` 처럼 쓴다.
#
# ★ 손으로 적지 않는다 — s8_translate.LANGS 가 유일한 출처다. 예전에 여기에
#   따로 적어 두었더니 언어를 더할 때마다 한쪽만 고쳐, 만들어 둔 자막이
#   **꼬리표를 못 알아봐 조용히 빠졌다.**
_TAG_TO_ISO: Dict[str, str] = {"ko": "kor", "kor": "kor"}
_LANG_NAME: Dict[str, str] = {"kor": "한국어"}
for _iso, _m in _LANGS.items():
    _TAG_TO_ISO[_m["tag"]] = _iso
    _TAG_TO_ISO[_iso] = _iso
    _LANG_NAME[_iso] = _m["native"]


def find_tracks(srt_dir: Path, default_srt: Path, default_lang: str = "kor"
                ) -> List[Tuple[Path, str]]:
    """04_자막 폴더에서 자막 트랙을 모은다.

    `<이름>.srt`        → 기본 언어
    `<이름>.ru.srt`     → 러시아어
    `<이름>.en.srt`     → 영어
    """
    out: List[Tuple[Path, str]] = []
    seen: set = set()
    if default_srt.is_file():
        out.append((default_srt, default_lang))
        seen.add(default_srt.resolve())

    if srt_dir.is_dir():
        for f in sorted(srt_dir.glob("*.srt")):
            if f.resolve() in seen:
                continue
            m = re.search(r"\.([A-Za-z]{2,3})\.srt$", f.name)
            tag = (m.group(1).lower() if m else "")
            iso = _TAG_TO_ISO.get(tag)
            if not iso:
                continue          # 꼬리표를 못 읽으면 건드리지 않는다
            out.append((f, iso))
            seen.add(f.resolve())
    return out


def copy_sidecar(src: Path, dst_dir: Path) -> Path:
    """SRT 사이드카를 넘겨줄 폴더로 옮긴다 — **UTF-8 BOM 을 붙여서.**

    ★ BOM 이 없으면 플레이어가 인코딩을 알아맞히려 들고, **한국어에서 유독 틀린다.**
      한국어 UTF-8 을 cp949 로 잘못 읽으면 `젙 샗 瑜` 같은 **그럴듯한 한글 음절**이
      나와서 감지기가 「한글이 나왔으니 맞다」고 믿는다. 러시아어를 같은 식으로
      읽으면 아무도 안 쓰는 한자가 쏟아져 감지기가 스스로 되돌린다 — 그래서
      **러시아어만 멀쩡하고 한국어만 깨지는** 일이 실제로 벌어졌다.

      BOM 세 바이트(EF BB BF)가 있으면 감지기가 아예 안 돈다. VLC·PotPlayer·곰·
      Windows Media Player 가 전부 이것을 먼저 본다.

    ★ 04_자막의 원본에는 붙이지 않는다. 그쪽은 단계의 기록이고 ffmpeg·번역이
      읽는 자리다. BOM 은 **넘겨주는 사본에만** 붙인다.
    """
    dst = dst_dir / src.name
    dst.write_bytes(_BOM + src.read_bytes().lstrip(_BOM))
    return dst


def run(mp4: Path, srt: Path, *, lang: str = "kor",
        extra: Optional[List[Tuple[Path, str]]] = None,
        on_log: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """`srt` 는 기본 자막. `extra` 는 (파일, ISO코드) 목록 — 없으면 폴더에서 찾는다."""
    log = on_log or (lambda s: None)
    mp4, srt = Path(mp4), Path(srt)
    if not mp4.is_file():
        raise FileNotFoundError(f"영상이 없습니다: {mp4}")

    tracks = extra if extra is not None else find_tracks(srt.parent, srt, lang)
    tracks = [(Path(f), l) for f, l in tracks if Path(f).is_file()]

    tmp = mp4.with_suffix(".muxing.mp4")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp4)]
    for f, _l in tracks:
        cmd += ["-i", str(f)]
    # ★ `-map 0` 만 쓰면 **이미 얹혀 있던 자막 트랙이 남아 두 벌이 된다.**
    #   번역이 빌드 뒤에 끝나 다시 얹는 일이 실제로 있으므로(그때 재렌더는 낭비다)
    #   이 단계는 몇 번을 돌려도 결과가 같아야 한다. 원본의 자막만 덜어낸다 —
    #   자막의 진실은 항상 04_자막 폴더에 있고, MP4 안의 것은 그 사본일 뿐이다.
    cmd += ["-map", "0", "-map", "-0:s"]
    for i in range(len(tracks)):
        cmd += ["-map", str(i + 1)]
    cmd += ["-c", "copy"]
    if tracks:
        cmd += ["-c:s", "mov_text"]
    for i, (_f, l) in enumerate(tracks):
        cmd += [f"-metadata:s:s:{i}", f"language={l}",
                f"-metadata:s:s:{i}", f"title={_LANG_NAME.get(l, l)}"]
    # ★ +faststart — moov 아톰을 파일 앞으로 옮긴다.
    #
    #   실측(2026-09-01, 16분 37MB): HyperFrames 가 낸 MP4 는 `ftyp free mdat moov`
    #   순서로, **moov 가 파일 끝에 있었다.** 그러면 재생하려는 쪽이 먼저 파일
    #   꼬리를 받아 와야 한다 — 브라우저는 Range 요청으로 알아서 하지만, 그걸
    #   못 하는 플레이어·LMS·CDN 에서는 다 받을 때까지 멈춘 것처럼 보인다.
    #   자막을 얹을 때 이미 -c copy 로 한 번 다시 쓰므로 **공짜다**(재인코딩 없음).
    #
    #   ★ 자막이 없어도 이 한 가지 때문에 다시 쓴다. 넘겨줄 파일이니까.
    cmd += ["-movflags", "+faststart"]
    cmd.append(str(tmp))
    if not tracks:
        log("  자막 파일이 없습니다 — faststart 만 적용합니다.")

    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       creationflags=_NO_WINDOW, timeout=600)
    if r.returncode != 0 or not tmp.is_file():
        # 실패해도 영상은 이미 나왔다 — 죽이지 않는다. SRT 사이드카는 그대로 있다.
        log(f"  자막 트랙 얹기 실패 — SRT 는 그대로 있습니다: "
            f"{(r.stderr or '').strip()[:160]}")
        tmp.unlink(missing_ok=True)
        return {"muxed": False, "tracks": [], "error": (r.stderr or "").strip()[:300]}

    shutil.move(str(tmp), str(mp4))
    if not tracks:
        log("  faststart 적용 — moov 를 앞으로 옮겼습니다.")
        return {"muxed": False, "tracks": [], "faststart": True}
    names = " · ".join(_LANG_NAME.get(l, l) for _f, l in tracks)
    log(f"  자막 트랙 {len(tracks)}개를 얹었습니다 ({names}) — 플레이어에서 고를 수 있습니다.")
    return {"muxed": True, "tracks": [l for _f, l in tracks]}
