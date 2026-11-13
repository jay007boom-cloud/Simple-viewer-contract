# Simple Viewer Contract — Rev.0

**Parsing for Easy Reading**: a Windows contract reader that converts a local document into Markdown, structured JSON, and a linked HTML reader for Edge or Chrome.

Rev.0 is the saved `_Rev2.2` program version from **before the Astra enhancements**. The program files are copied without modification; `REVISION.json` records their SHA-256 hashes. The Git tag `Rev.0` identifies this snapshot. Later local development is not included in this revision.

## 실행 방법

1. Windows에서 Python 3.12와 Edge 또는 Chrome을 준비합니다.
2. 이 저장소를 내려받고 압축을 풉니다.
3. 폴더 안에서 PowerShell을 열고 의존성을 설치합니다.

```powershell
python -m pip install -r requirements.txt
```

4. `ContractViewer_Rev22.exe`를 실행해 문서를 선택하고 **One-stop: Parse & Open**을 누릅니다. EXE는 데스크톱 실행 화면이며 문서 변환에는 설치된 Python을 사용합니다.

PowerShell로 직접 처리할 수도 있습니다.

```powershell
& '.\OneStop-Contract.ps1' -SourceFile 'C:\Contracts\Agreement.pdf'
& '.\OneStop-Contract.ps1' -SourceFile 'C:\Contracts\Agreement.docx' -OpenInChrome
```

## 기능

- 문서별 작업 폴더 생성, 원문 보존, Markdown 추출 및 JSON 구조화
- 조항·정의 검색, 내부 참조와 정의 미리보기, 오른쪽 패널
- 전문 읽기, 읽기 폭과 패널 폭 조절, 이전 위치로 돌아가기
- 선택 구간 하이라이트와 메모
- Google 음성 읽기와 영·한 해설을 별도 실행
- 초급·중급·고급 해설 수준 설정

Rev.0의 기능과 동작을 그대로 보존했습니다. 이후 로컬 버전의 목록 화면, 추가 읽기 설정 및 폭 조절 재작업은 이 스냅샷에 포함되지 않습니다.

## 처리 구조

```text
원문 → 전처리 / Markdown 추출 → parsed/contract.json → HTML 읽기 화면
```

```text
Contracts/<document>/
  source/                 원문 및 필요한 작업용 DOCX
  extraction/             Markdown 및 변환 기록
  parsed/contract.json    구조화 계약서
  output/                 HTML, 정규화 JSON 및 실행 파일
  operation-report.json   처리 경로와 소요 시간
```

일반 텍스트 PDF와 Office는 MarkItDown을 사용합니다. 스캔 PDF는 `Setup-MinerU.ps1`로 로컬 OCR 도구를 설치한 후 처리합니다. 기존 `.doc` 전처리에는 Microsoft Word가 필요합니다. 복잡한 표와 불규칙한 조항 경계는 원문 대조가 필요합니다.

수정한 Markdown을 다시 파싱할 때:

```powershell
& '.\OneStop-Contract.ps1' -ContractFolder '.\Contracts\Agreement' -Reparse
```

## 음성과 해설

`Set-GoogleTTSKey.ps1`을 로컬에서 실행해 Google Gemini API 키를 입력합니다. 키는 Windows 사용자 암호화 저장소에 보관됩니다. 계약서의 `output/Open-with-Google-TTS.cmd`를 통해 열고 문장을 선택합니다.

- 우클릭 또는 **Read aloud**: 영어 음성 읽기
- **Explain**: 영어·한국어 해설과 계약 엔지니어 관점
- 상단 설정: 해설 수준과 음성 모드

사용자가 요청한 선택 문장을 Google API로 전송합니다. HTML을 직접 여는 `file://` 방식에서는 Google 기능이 활성화되지 않습니다.

## 저장소 구성

공개 업로드에는 프로그램과 실행 안내가 들어 있습니다. 실제 계약서 원문·추출 결과·계약서 JSON·개인 메모·API 키는 로컬 작업 데이터이며 저장소에서 제외합니다.

이 버전의 기준은 `REVISION.json`과 Git tag **Rev.0**입니다.
