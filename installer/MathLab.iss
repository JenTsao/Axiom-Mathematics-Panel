; MathLab Windows 安装包脚本（Inno Setup 6.3+，建议 6.5）
;
; 前置：先在仓库根执行 pyinstaller mathlab.spec 生成 dist\MathLab\
; 编译：iscc /DAPP_VERSION=3.8.0 installer\MathLab.iss
;   CI（release.yml）会从 mathlab/utils/version.py 提取版本号传入 APP_VERSION；
;   未传时回退 0.0.0，仅用于本地语法验证。
; 产物：dist\MathLab-<版本>-Windows-Setup.exe
;
; installer\languages\ChineseSimplified.isl 取自 jrsoftware/issrc 仓库
; （Inno Setup License 允许随安装脚本一同分发，维护者署名保留在文件头）；
; installer\LICENSE.txt 由根目录 LICENSE（Markdown）转出的纯文本，
; 许可证变更时需同步重新生成，保持与 LICENSE 全文一致。

#ifndef APP_VERSION
#define APP_VERSION "0.0.0"
#endif

#define MyAppName "MathLab"
#define MyAppExeName "MathLab.exe"
#define MyAppPublisher "jencao"
; 必须与 git remote 一致（原值写的是 jencaoking，点击"关于"里的网址会 404）
#define MyAppURL "https://github.com/JenTsao/Axiom-Mathematics-Panel"

[Setup]
; AppId 固定不变：同一 AppId 的重新安装会被识别为升级而非并存安装
AppId={{E9BB8CE8-39BF-426D-A540-CEE66FADE1CD}
AppName={#MyAppName}
AppVersion={#APP_VERSION}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
SetupIconFile=..\mathlab\resources\icons\app_icon.ico
; 输出与 PyInstaller 产物同在仓库根 dist\ 下
OutputDir=..\dist
OutputBaseFilename=MathLab-{#APP_VERSION}-Windows-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes

[Languages]
; 双语安装界面：定义多个语言后 Inno 自动弹出"选择安装语言"页；
; 中文条目串联 Default.isl，缺失消息自动回落英文，兼容不同 Inno 版本
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl,languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller ONEDIR 全量产物（MathLab.exe + _internal\）
; Excludes：dist\ 可能被本地旧的运行残留污染（曾出现过 7 月的 crash.log 与 logs\ 被打进安装包），
; 按文件名排除所有日志类文件；纯源码构建时 dist\ 里本不该有 *.log。
Source: "..\dist\MathLab\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "*.log,crash.log"
; CASAL 许可证随安装目录分发（许可证 §2.2 / §7 要求保留全文）
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 清理运行时生成的缓存 / 日志 / 崩溃报告，避免卸载残留
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\crash.log"
Type: filesandordirs; Name: "{app}\mathlab\webcache"
Type: filesandordirs; Name: "{app}\mathlab\logs"
Type: filesandordirs; Name: "{app}\mathlab\autosave"
