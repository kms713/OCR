; 시험지 OCR 변환 — 설치 파일 설정 (Inno Setup 6 / 7)
; build_windows.bat 이 마지막 단계에서 자동으로 사용합니다.
; 결과: installer\ExamOCR_Setup.exe

#define AppName "시험지 OCR 변환"
#define AppVersion "1.0.0"
#define AppExe "ExamOCR.exe"

[Setup]
; AppId는 바꾸지 마세요. 같아야 새 버전이 기존 설치 위에 덮어 설치됩니다.
AppId={{0AB9C8CC-8E5A-4AB8-B26E-F8E85C9E3FC9}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=비원영어학원·오길수학
VersionInfoVersion={#AppVersion}.0
; 설치 위치 고정: C:\Program Files\ExamOCR (영문 경로)
DefaultDirName={autopf}\ExamOCR
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
OutputDir=installer
OutputBaseFilename=ExamOCR_Setup
Compression=lzma2/normal
SolidCompression=yes
LZMANumBlockThreads=4

[Languages]
#ifexist AddBackslash(CompilerPath) + "Languages\Korean.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Files]
Source: "dist\ExamOCR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"

[Run]
; 관리자 권한이 아닌 평소 사용자 권한으로 실행 (로그·설정 위치가 평소 실행과 같도록)
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
function IsProcessorFeaturePresent(Feature: Cardinal): Integer;
  external 'IsProcessorFeaturePresent@kernel32.dll stdcall';

{ 엔진은 AVX 명령이 없는 CPU에서 실행되지 않는다.
  38번(SSE4.2)이 '있음'으로 나올 때만 판단한다. (Windows 10 2004 이전에는 이 번호들을 몰라서 항상 '없음'을 돌려줌)
  AVX는 있고 AVX2는 없는 CPU는 프로그램이 처음 실행될 때 실제로 시험해서 판단한다. }
function InitializeSetup(): Boolean;
begin
  Result := True;
  if (IsProcessorFeaturePresent(38) <> 0) and (IsProcessorFeaturePresent(39) = 0) then
  begin
    MsgBox('이 컴퓨터는 CPU 사양이 낮아 ''{#AppName}''을(를) 사용할 수 없습니다.' + #13#10 +
           '다른 컴퓨터에 설치해 주세요.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;
