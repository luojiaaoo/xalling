; Xalling 安装程序脚本 (Inno Setup 6)
; 先运行 .\script\package_windows.bat 生成 dist\Xalling\，再由 ISCC 编译本脚本。
; 版本号需与 pyproject.toml 保持一致。

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "Xalling"

[Setup]
AppId={{A9C5B2D1-4E6F-4A3B-8C7D-2E1F0A9B8C7D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=AI Development Center
DefaultDirName={autopf}\Xalling
DisableWelcomePage=no
DisableDirPage=no
UsePreviousAppDir=yes
DefaultGroupName=Xalling
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Xalling-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\Xalling.exe
SetupIconFile=..\favicon.ico

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Xalling-DataSetup.exe"; Flags: dontcopy
Source: "..\dist\Xalling\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; AfterInstall: LogInstalledFile

[Icons]
Name: "{group}\Xalling"; Filename: "{app}\Xalling.exe"
Name: "{group}\Xalling Server"; Filename: "{app}\Xalling-Server.exe"
Name: "{group}\{cm:UninstallProgram,Xalling}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Xalling"; Filename: "{app}\Xalling.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Xalling.exe"; Description: "{cm:LaunchProgram,Xalling}"; Flags: nowait postinstall skipifsilent

[Code]
const
  PreviousUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{A9C5B2D1-4E6F-4A3B-8C7D-2E1F0A9B8C7D}_is1';
  LogSetRedraw = $000B;
  LogGetTextLength = $000E;
  LogSetSelection = $00B1;
  LogReplaceSelection = $00C2;
  LogSetTextLimit = $00C5;
  LogVerticalScroll = $0115;
  LogHorizontalScroll = $0114;

var
  DataDirPage: TInputDirWizardPage;
  MigrationModePage: TInputOptionWizardPage;
  MigrationLogMemo: TNewMemo;
  ChangeDataDir: TNewCheckBox;
  PreviousInstallRemoved: Boolean;
  HelperResultFile, ExistingDataDir, MigrationLogFile: String;
  InstalledFileCount: Integer;
  LastLogPaintTick: DWORD;
  PendingInstallerLog: String;

function GetTickCount: DWORD;
  external 'GetTickCount@kernel32.dll stdcall';

{ Inno Setup 6 runs a 32-bit installer, including on 64-bit Windows. }
function AppendLogText(Handle: HWND; Msg: UINT; WParam: LongWord; Text: String): Longint;
  external 'SendMessageW@user32.dll stdcall';

function RedrawLogWindow(Handle: HWND; Rect, Region: LongWord; Flags: UINT): Integer;
  external 'RedrawWindow@user32.dll stdcall';

function SelectedMigrationMode: String;
begin
  Result := 'copy';
  if MigrationModePage <> nil then
    if MigrationModePage.SelectedValueIndex = 1 then
      Result := 'move';
end;

function SelectedMigrationModeLabel: String;
begin
  if SelectedMigrationMode = 'copy' then
    Result := '复制并校验后删除旧目录'
  else
    Result := '直接剪切（请勿中断）';
end;

procedure RefreshInstallerLog;
var
  TextLength: Integer;
begin
  if (MigrationLogMemo = nil) or (PendingInstallerLog = '') then
    Exit;
  TextLength := SendMessage(MigrationLogMemo.Handle, LogGetTextLength, 0, 0);
  { Keep all lines and paint only after the batch is appended and scrolled. }
  SendMessage(MigrationLogMemo.Handle, LogSetRedraw, 0, 0);
  try
    SendMessage(MigrationLogMemo.Handle, LogSetSelection, TextLength, TextLength);
    AppendLogText(MigrationLogMemo.Handle, LogReplaceSelection, 0, PendingInstallerLog);
    PendingInstallerLog := '';
    SendMessage(MigrationLogMemo.Handle, LogVerticalScroll, 7, 0); { SB_BOTTOM }
    SendMessage(MigrationLogMemo.Handle, LogHorizontalScroll, 6, 0); { SB_LEFT }
  finally
    SendMessage(MigrationLogMemo.Handle, LogSetRedraw, 1, 0);
    { RDW_UPDATENOW also paints before a blocking helper/Sleep/page change. }
    RedrawLogWindow(MigrationLogMemo.Handle, 0, 0, $585);
  end;
  LastLogPaintTick := GetTickCount;
end;

procedure AppendInstallerLog(const S: String);
var
  Tick: DWORD;
begin
  if Trim(S) = '' then
    Exit;
  Log(S);
  if MigrationLogMemo = nil then
    Exit;
  PendingInstallerLog := PendingInstallerLog + S + #13#10;
  Tick := GetTickCount;
  { Keep every path, but avoid forcing a synchronous repaint for every file. }
  if (LastLogPaintTick = 0) or (Tick < LastLogPaintTick) or
    (Tick - LastLogPaintTick >= 100) then
    RefreshInstallerLog;
end;

procedure LogInstalledFile;
var
  FileName: String;
begin
  InstalledFileCount := InstalledFileCount + 1;
  FileName := ExpandConstant(CurrentFilename);
  AppendInstallerLog('[安装] ' + FileName);
end;

procedure MigrationOutput(const S: String; const Error, FirstLine: Boolean);
begin
  AppendInstallerLog(S);
end;

function RunDataHelper(Action, Directory: String): String;
var
  Arguments: String;
  ExitCode: Integer;
begin
  Result := '';
  DeleteFile(HelperResultFile);
  Arguments := Action + ' --result "' + HelperResultFile + '"';
  Arguments := Arguments + ' --mode ' + SelectedMigrationMode;
  if Directory <> '' then
    Arguments := Arguments + ' --target "' + RemoveBackslashUnlessRoot(Directory) + '"';
  if Action = 'migrate' then
    Arguments := Arguments + ' --log "' + MigrationLogFile + '"';
  if not ExecAndLogOutput(ExpandConstant('{tmp}\Xalling-DataSetup.exe'), Arguments, '',
    SW_SHOWNORMAL, ewWaitUntilTerminated, ExitCode, @MigrationOutput) then
  begin
    Result := '无法启动数据迁移工具。';
    Exit;
  end;
  if not FileExists(HelperResultFile) then
    Result := '数据迁移工具未返回结果。'
  else
    Result := GetIniString('result', 'error', '', HelperResultFile);
  if (ExitCode <> 0) and (Result = '') then
    Result := '数据迁移工具执行失败。';
end;

procedure ChangeDataDirClick(Sender: TObject);
begin
  DataDirPage.Edits[0].Enabled := ChangeDataDir.Checked;
  DataDirPage.Buttons[0].Enabled := ChangeDataDir.Checked;
end;

procedure InitializeWizard;
var
  RequestedDataDir, RequestedMode, Description, Error: String;
begin
  WizardForm.FilenameLabel.Visible := False;
  ExtractTemporaryFile('Xalling-DataSetup.exe');
  HelperResultFile := ExpandConstant('{tmp}\xalling-data-result.ini');
  Error := RunDataHelper('inspect', '');
  if Error <> '' then
    RaiseException(Error);
  ExistingDataDir := GetIniString('result', 'source', '', HelperResultFile);
  MigrationLogFile := ExtractFileDir(ExpandFileName(AddBackslash(GetEnv('USERPROFILE')) +
    'xalling-paths.toml')) + '\xalling-install-migration.log';
  Description := '模型配置、会话、日志、附件和知识库将保存在此目录。';
  if GetIniString('result', 'found', '0', HelperResultFile) = '1' then
    Description := Description + #13#10 + '发现已有用户目录：' + ExistingDataDir;
  Description := Description + #13#10 +
    '更改路径后可选择剪切或复制迁移，迁移后磁盘必须剩余超过 1 GB（1024 MB）。';
  RequestedDataDir := ExpandConstant('{param:DATADIR|}');
  DataDirPage := CreateInputDirPage(wpSelectDir,
    '数据目录', '请选择 Xalling 数据的保存位置', Description, False, '');
  DataDirPage.Add('数据目录（迁移目标必须为空目录）：');
  DataDirPage.Values[0] := ExistingDataDir;
  if RequestedDataDir <> '' then
    DataDirPage.Edits[0].Text := RequestedDataDir;

  ChangeDataDir := TNewCheckBox.Create(DataDirPage);
  ChangeDataDir.Parent := DataDirPage.Surface;
  ChangeDataDir.Left := DataDirPage.Edits[0].Left;
  ChangeDataDir.Top := DataDirPage.Edits[0].Top + DataDirPage.Edits[0].Height + ScaleY(16);
  ChangeDataDir.Width := DataDirPage.SurfaceWidth;
  ChangeDataDir.Caption := '设置此目录，路径改变时自动迁移已有数据';
  ChangeDataDir.Checked := not FileExists(AddBackslash(GetEnv('USERPROFILE')) + 'xalling-paths.toml')
    or (RequestedDataDir <> '');
  ChangeDataDir.OnClick := @ChangeDataDirClick;
  ChangeDataDirClick(ChangeDataDir);

  MigrationModePage := CreateInputOptionPage(DataDirPage.ID,
    '迁移方式', '请选择用户数据迁移方式',
    '剪切期间请勿停止安装或关闭电脑，否则可能导致数据分散或不完整。' + #13#10 +
    '复制更稳妥，但需要额外空间；复制并校验成功、更新配置后会删除旧目录。',
    True, False);
  MigrationModePage.Add('复制后删除旧目录（推荐，更稳妥，占用额外空间）');
  MigrationModePage.Add('直接剪切（同磁盘可快速移动，请勿中断）');
  MigrationModePage.SelectedValueIndex := 0;
  RequestedMode := ExpandConstant('{param:MIGRATIONMODE|copy}');
  if RequestedMode = 'move' then
    MigrationModePage.SelectedValueIndex := 1
  else if RequestedMode <> 'copy' then
    RaiseException('MIGRATIONMODE 必须为 copy 或 move。');

  MigrationLogMemo := TNewMemo.Create(WizardForm);
  MigrationLogMemo.Parent := WizardForm.InstallingPage;
  MigrationLogMemo.Left := WizardForm.ProgressGauge.Left;
  MigrationLogMemo.Top := WizardForm.ProgressGauge.Top + WizardForm.ProgressGauge.Height + ScaleY(12);
  MigrationLogMemo.Width := WizardForm.ProgressGauge.Width;
  MigrationLogMemo.Height := WizardForm.InstallingPage.ClientHeight - MigrationLogMemo.Top;
  MigrationLogMemo.ReadOnly := True;
  MigrationLogMemo.WordWrap := False;
  MigrationLogMemo.ScrollBars := ssBoth;
  SendMessage(MigrationLogMemo.Handle, LogSetTextLimit, $7FFFFFFE, 0);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = MigrationModePage.ID then
    Result := not ChangeDataDir.Checked or not DirExists(ExistingDataDir) or
      (CompareText(RemoveBackslashUnlessRoot(DataDirPage.Values[0]),
        RemoveBackslashUnlessRoot(ExistingDataDir)) = 0);
end;

function ValidateDataDir: String;
var
  Directory: String;
begin
  Result := '';
  if not ChangeDataDir.Checked then
    Exit;
  Directory := Trim(DataDirPage.Edits[0].Text);
  StringChangeEx(Directory, '/', '\', True);
  if not (((Length(Directory) >= 3) and (Directory[2] = ':') and
    (Directory[3] = '\')) or (Copy(Directory, 1, 2) = '\\')) then
  begin
    Result := '请选择绝对路径，例如 D:\XallingData。';
    Exit;
  end;
  if FileExists(Directory) then
  begin
    Result := '该路径是文件，请选择一个目录。';
    Exit;
  end;
  DataDirPage.Values[0] := ExpandFileName(Directory);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if (CurPageID <> DataDirPage.ID) and (CurPageID <> MigrationModePage.ID) then
    Exit;
  Error := ValidateDataDir;
  if Error <> '' then
  begin
    MsgBox(Error, mbError, MB_OK);
    Result := False;
  end;
end;

function UninstallPreviousInstallation(RootKey: Integer): String;
var
  Command, Uninstaller, Arguments: String;
  ClosingQuote, ExitCode: Integer;
begin
  Result := '';
  if not RegKeyExists(RootKey, PreviousUninstallKey) then
    Exit;
  if not RegQueryStringValue(RootKey, PreviousUninstallKey, 'UninstallString', Command) then
  begin
    Result := '发现已有 Xalling 安装，但无法读取卸载程序。请先手动卸载后重试。';
    Exit;
  end;
  Command := Trim(Command);
  if Copy(Command, 1, 1) = '"' then
  begin
    Delete(Command, 1, 1);
    ClosingQuote := Pos('"', Command);
    Uninstaller := Copy(Command, 1, ClosingQuote - 1);
  end
  else
  begin
    ClosingQuote := Pos(' ', Command);
    if ClosingQuote = 0 then
      Uninstaller := Command
    else
      Uninstaller := Copy(Command, 1, ClosingQuote - 1);
  end;
  if not FileExists(Uninstaller) then
  begin
    Result := '发现已有 Xalling 安装，但卸载程序不存在：' + Uninstaller;
    Exit;
  end;
  AppendInstallerLog('[安装] 发现已有 Xalling 安装，先卸载再安装，不区分版本号：' + Uninstaller);
  WizardForm.PreparingLabel.Caption := '正在卸载已有 Xalling，用户数据将保留…';
  WizardForm.PreparingLabel.Update;
  Arguments := '/SILENT /SUPPRESSMSGBOXES /NORESTART';
  if WizardSilent then
    Arguments := '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART';
  if not Exec(Uninstaller, Arguments, ExtractFileDir(Uninstaller), SW_SHOWNORMAL,
    ewWaitUntilTerminated, ExitCode) then
    Result := '无法启动已有 Xalling 的卸载程序。'
  else if ExitCode <> 0 then
    Result := Format('已有 Xalling 卸载失败（退出码 %d），已停止安装。', [ExitCode])
  else if RegKeyExists(RootKey, PreviousUninstallKey) then
    Result := '已有 Xalling 尚未完成卸载，已停止安装，请先完成卸载后重试。'
  else
    AppendInstallerLog('[安装] 已有 Xalling 卸载完成，继续安装。');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := ValidateDataDir;
  if Result <> '' then
    Exit;
  if CheckForMutexes('Global\Xalling.SingleInstance') then
  begin
    Result := 'Xalling 正在运行，请关闭桌面和无头服务后重试。';
    Exit;
  end;
  if PreviousInstallRemoved then
    Exit;
  Result := UninstallPreviousInstallation(HKCU32);
  if (Result = '') and IsWin64 then
    Result := UninstallPreviousInstallation(HKCU64);
  if Result = '' then
    Result := UninstallPreviousInstallation(HKLM32);
  if (Result = '') and IsWin64 then
    Result := UninstallPreviousInstallation(HKLM64);
  PreviousInstallRemoved := Result = '';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + MemoGroupInfo + NewLine + MemoTasksInfo + NewLine + NewLine;
  Result := Result + '若检测到已有 Xalling，将先卸载再安装（用户数据保留）。' + NewLine;
  if ChangeDataDir.Checked then
  begin
    Result := Result + '数据目录：' + DataDirPage.Values[0] + NewLine +
      '迁移方式：' + SelectedMigrationModeLabel + NewLine +
      '开始迁移后统计数据大小并检查磁盘空间，通过后立即迁移。'
  end
  else
    Result := Result + '保留现有数据目录：' + ExistingDataDir;
end;

procedure ShowInstallSummary(const DataStatus: String);
var
  DataDirectory: String;
begin
  DataDirectory := ExistingDataDir;
  if ChangeDataDir.Checked then
    DataDirectory := DataDirPage.Values[0];
  AppendInstallerLog('[总结] Xalling {#MyAppVersion} 安装完成');
  AppendInstallerLog('[总结] 程序目录：' + ExpandConstant('{app}'));
  AppendInstallerLog(Format('[总结] 已安装 %d 个程序文件', [InstalledFileCount]));
  AppendInstallerLog('[总结] 数据目录：' + DataDirectory);
  AppendInstallerLog('[总结] 用户数据：' + DataStatus);
  if FileExists(MigrationLogFile) then
    AppendInstallerLog('[总结] 迁移日志：' + MigrationLogFile);
  RefreshInstallerLog;
  if not WizardSilent then
    Sleep(4000);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Error, Warning, DataStatus: String;
begin
  if CurStep = ssInstall then
  begin
    InstalledFileCount := 0;
    LastLogPaintTick := 0;
    AppendInstallerLog('[安装] 开始安装程序文件：' + ExpandConstant('{app}'));
    RefreshInstallerLog;
    Exit;
  end;
  if CurStep <> ssPostInstall then
    Exit;
  AppendInstallerLog(Format('[安装] 程序文件、快捷方式和注册信息安装完成，共安装 %d 个文件。', [InstalledFileCount]));
  if not ChangeDataDir.Checked then
  begin
    ShowInstallSummary('保留原数据目录，未迁移');
    Exit;
  end;
  AppendInstallerLog('[迁移] 开始计算用户数据大小和可用空间，通过后立即迁移…');
  RefreshInstallerLog;
  Error := RunDataHelper('migrate', DataDirPage.Values[0]);
  if Error <> '' then
  begin
    AppendInstallerLog('[总结] 程序文件已安装，用户数据迁移失败：' + Error);
    RefreshInstallerLog;
    RaiseException('数据目录迁移失败：' + Error);
  end;
  Warning := GetIniString('result', 'cleanup_warning', '', HelperResultFile);
  if Warning <> '' then
  begin
    Log(Warning);
    SuppressibleMsgBox(Warning, mbInformation, MB_OK, IDOK);
  end;
  AppendInstallerLog('[迁移] 迁移完成。');
  DataStatus := '数据目录已设置，无需迁移';
  if GetIniString('result', 'moving', '0', HelperResultFile) = '1' then
  begin
    if SelectedMigrationMode = 'copy' then
      DataStatus := '复制迁移完成，旧目录已删除'
    else
      DataStatus := '剪切迁移完成';
  end;
  if Warning <> '' then
    DataStatus := '迁移完成，旧目录存在残留，请清理';
  ShowInstallSummary(DataStatus);
end;
