; CS2 Customizer Inno Setup 安装脚本(onedir 形态)
; 编译(推荐,版本号自动取自 config.VERSION、ISCC.exe 自动定位):
;     python build_tools\build_release.py --mode onedir --installer-only
; 前置: ① python build_tools\build_release.py --mode onedir
;       ② python build_tools\make_installer_assets.py(品牌向导图,已入库可不重跑)
; 设计要点:
;  - WizardStyle=modern + 深紫品牌向导图,与应用深色主题同视觉语言
;  - 普通权限安装到 {localappdata}\CS2Customizer(与 2.1.3 降权方向一致,零 UAC)
;  - 升级时自动请求关闭运行中的 CS2 Customizer(CloseApplications)
;  - 卸载清开机自启注册表,保留用户配置(%LOCALAPPDATA%\CS2Customizer 数据)

; 版本号只能由外部传入,这里**故意不设兜底常量**。
; 原先是 #ifndef 回落到一个写死的字面量,那会造成静默事故:漏传 /DAppVersion 时
; Inno 会拿这个过期版本去打包磁盘上同名的旧 release 目录,产出一个内部完全自洽、
; 装出来却是上一版的安装包,而且零报错。宁可在这里响亮地失败。
#ifndef AppVersion
  #error 未指定版本号。请用 python build_tools\build_release.py --mode onedir --installer-only(自动带版本号),或手工加 /DAppVersion=<版本>
#endif
#define AppName "CS2 Customizer"
#define AppDirName AppName + " " + AppVersion
#define AppExeName AppName + ".exe"
#define AppPublisher "孤帆 (gufan)"
#define AppURL "https://github.com/gufan0000/cs2-customizer"

[Setup]
; AppId 是 Inno 判定"同一产品"的唯一依据:同 AppId 会被当成升级——沿用原目录、
; 覆盖注册项、卸载其一会带走另一个的记录。本项目与其前身是两个独立产品,
; 必须各用各的 AppId,否则装了开源版会把闭源版"升级"掉。开源化时重新生成。
AppId={{8109C3C7-BF9F-4C86-A63E-4DDAD3B03BC0}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={localappdata}\CS2Customizer\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release\installer
; 产物名走纯 ASCII 无空格:GitHub Release 附件会把空格替成点,中文名在部分
; 下载器/浏览器上会被 URL 编码成乱码。
OutputBaseFilename=CS2Customizer-Setup-{#AppVersion}
; 与项目根 icon.ico **字节相同**,同由 build_tools/make_app_icon.py 一次出齐。
; 历史:原 icon.ico 是伪装成 .ico 的单帧 PNG,Inno 不接受 PNG 帧,于是有人手工
; "重铸"了这一份——一个没人记得的手工步骤。现在生成器统一写 32bpp BMP 帧,
; 三个路径一次出齐,这里保留独立文件名只为不动 Inno 的既有引用。
SetupIconFile=installer_assets\setup_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; modern 风格默认跳过欢迎页;品牌大图就在欢迎/完成页,必须显式打开
DisableWelcomePage=no
; 升级体验:检测到旧安装(同 AppId)时自动沿用原目录并跳过选目录页——
; 用户下载新安装包双击,一路"下一步"即完成覆盖升级,无需找原文件夹
DisableDirPage=auto
UsePreviousAppDir=yes
WizardImageFile=installer_assets\wizard_large.bmp
WizardSmallImageFile=installer_assets\wizard_small.bmp
WizardImageStretch=yes
ShowLanguageDialog=no
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Messages]
chinesesimplified.WelcomeLabel1=欢迎安装 [name]
chinesesimplified.WelcomeLabel2=即将在你的电脑上安装 [name/ver]。%n%nCS2 游戏体验增强:准心、击杀音效、自定闪光、开镜放大、音乐联动,一站搞定。%n%n建议先关闭正在运行的 CS2 Customizer 再继续。
chinesesimplified.FinishedHeadingLabel=安装完成!
chinesesimplified.FinishedLabel=[name] 已经装好。开始享受更带感的对局吧——记得在软件里把 CS2 目录配置好。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[InstallDelete]
; 覆盖升级时清掉旧版本遗留:exe 名带版本号,不清会双 exe 并存
; (_internal 整目录重铺,顺带清陈旧库文件)
Type: files; Name: "{app}\CS2 Customizer*.exe"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; onedir 整目录(exe + _internal),递归收取
Source: "..\release\{#AppDirName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[Registry]
; 卸载时移除开机自启(若用户开过;键名必须与 core/utils/autostart.py 的 _VALUE_NAME 一致)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "CS2Customizer"; Flags: dontcreatekey uninsdeletevalue

[UninstallDelete]
; 程序目录内运行期残留(日志/缓存不在此处,用户配置在 %LOCALAPPDATA%\CS2Customizer,保留)
Type: filesandordirs; Name: "{app}\_internal"


[Code]
{ 安装收尾:把"开机自启"注册表项迁移指向新版固定名 exe。
  - 仅当用户此前开过自启(值已存在)才改,绝不主动新增自启;
  - 这会清掉指向旧版/早期单 exe 路径的陈旧自启项,装完即生效(无需等 app 首次启动自愈)。 }
procedure CurStepChanged(CurStep: TSetupStep);
var
  RunKey, ValueName, OldCmd, NewCmd: String;
begin
  if CurStep = ssPostInstall then
  begin
    RunKey := 'Software\Microsoft\Windows\CurrentVersion\Run';
    ValueName := 'CS2Customizer';
    if RegQueryStringValue(HKEY_CURRENT_USER, RunKey, ValueName, OldCmd) then
    begin
      NewCmd := '"' + ExpandConstant('{app}\{#AppExeName}') + '"';
      if CompareText(Trim(OldCmd), NewCmd) <> 0 then
        RegWriteStringValue(HKEY_CURRENT_USER, RunKey, ValueName, NewCmd);
    end;
  end;
end;

{ 卸载时询问是否一并删除用户数据(配置/导入资源)。
  - 默认选"否"(MB_DEFBUTTON2):保留数据,方便重装后继续用;
  - 静默卸载(UninstallSilent)不弹窗、保持原行为=保留数据,不破坏既有 /VERYSILENT 验收。 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
  begin
    DataDir := ExpandConstant('{localappdata}\CS2Customizer');
    if DirExists(DataDir) then
    begin
      if MsgBox('是否同时删除 CS2 Customizer 的配置和导入的资源？' + #13#10 +
                '位置：' + DataDir + #13#10 + #13#10 +
                '选择“否”将保留你的设置，方便以后重装后继续使用。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
