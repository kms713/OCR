; 시험지 OCR 변환 (저사양용) — 설치 파일 설정 (Inno Setup 6 / 7)
; build_lite.bat 이 마지막 단계에서 자동으로 사용합니다.
; 결과: installer_lite\ExamOCR_Lite_Setup.exe
; 기본판과 따로 설치되며(다른 AppId·다른 폴더), 같은 PC에 함께 있어도 충돌하지 않습니다.

#define AppName "시험지 OCR 변환 (저사양용)"
#define AppVersion "1.0.0"
#define AppExe "ExamOCR.exe"

[Setup]
; AppId는 바꾸지 마세요. 같아야 새 버전이 기존 설치 위에 덮어 설치됩니다.
AppId={{41EDF31A-C090-4871-93B4-E1FDA08485A5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=비원영어학원·오길수학
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\ExamOCR_Lite
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
OutputDir=installer_lite
OutputBaseFilename=ExamOCR_Lite_Setup
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
Source: "dist\ExamOCR_Lite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent runasoriginaluser
