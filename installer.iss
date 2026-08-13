; VK Contest Analyzer — Inno Setup installer script
; Compile with: ISCC.exe installer.iss   (Inno Setup 6+)
; Expects dist\VKContestAnalyzer\ to already exist (run build.bat first).
;
; ── One-time per-machine setup ────────────────────────────────────────────
; This script needs vendor\dotnetfx\NDP48-x86-x64-AllOS-ENU.exe, which is
; NOT in git (it's ~115MB, over GitHub's 100MB file limit — see .gitignore).
; On a fresh checkout/machine, download it yourself before compiling:
;   1. Official Microsoft Support page:
;      https://support.microsoft.com/en-us/topic/microsoft-net-framework-4-8-offline-installer-for-windows-9d23f658-3b97-68ab-d013-aa3c3e7495e0
;      -> "https://go.microsoft.com/fwlink/?linkid=2088631" (offline installer)
;   2. Save it as vendor\dotnetfx\NDP48-x86-x64-AllOS-ENU.exe (relative to
;      this file) — create the vendor\dotnetfx\ folder if it doesn't exist.
; ISCC.exe will fail with a missing-source-file error if this isn't done.

#define MyAppName "VK Contest Analyzer"
#define MyAppVersion "26.7.24"
#define MyAppExeName "VKContestAnalyzer.exe"
#define MyAppSourceDir "dist\VKContestAnalyzer"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Explicit, even though {autopf} already implies it — the bundled .NET
; Framework repair installer requires elevation to run.
PrivilegesRequired=admin
OutputDir=dist\installer
OutputBaseFilename=VKContestAnalyzer_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
; PyInstaller's dist folder can be large with the bundled runtime —
; lzma2/solid compression keeps the installer reasonably sized anyway.

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; .NET Framework 4.8 offline (repair) installer — extracted to a temp
; folder at install time, not copied into the app's install directory.
Source: "vendor\dotnetfx\NDP48-x86-x64-AllOS-ENU.exe"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  NeedsReboot: Boolean;

function DotNet48Present: Boolean;
var
  Release: Cardinal;
begin
  // Release >= 528040 corresponds to .NET Framework 4.8 per Microsoft's
  // documented version table. This only proves the registry SAYS 4.8 is
  // installed — it doesn't prove CLR hosting actually works (the original
  // bug we chased was a corrupted install that still reported as present).
  // Trading a little certainty for not making every install sit through a
  // multi-minute repair pass when the machine is most likely fine.
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release)
            and (Release >= 528040);
end;

procedure RepairDotNet48;
var
  ResultCode: Integer;
  ExePath: String;
begin
  WizardForm.StatusLabel.Caption :=
    'Installing/repairing .NET Framework 4.8 — required for the app window. ' +
    'This can take several minutes; the progress bar below will show its status.';
  WizardForm.StatusLabel.Repaint;
  // Our own progress bar has nothing to report during the Exec call below
  // (it's a single blocking step), so switch it to an indeterminate
  // "busy" animation rather than leaving it looking frozen for several
  // minutes — that's what made this feel silent/stuck before.
  WizardForm.ProgressGauge.Style := npbstMarquee;

  ExtractTemporaryFile('NDP48-x86-x64-AllOS-ENU.exe');
  ExePath := ExpandConstant('{tmp}\NDP48-x86-x64-AllOS-ENU.exe');
  // /passive (not /q): shows the .NET installer's OWN progress UI so the
  // user sees it actually doing something, while still needing zero
  // clicks (unlike a fully interactive install).
  if Exec(ExePath, '/passive /norestart', '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) then
  begin
    // 0 = success, 3010/1641 = success but a reboot is needed before the
    // repaired runtime is fully active. Anything else: log and continue —
    // the app's own browser-fallback still works even if this didn't help.
    if (ResultCode = 3010) or (ResultCode = 1641) then
      NeedsReboot := True;
  end;

  WizardForm.ProgressGauge.Style := npbstNormal;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not DotNet48Present then
    RepairDotNet48;
end;

function NeedRestart: Boolean;
begin
  Result := NeedsReboot;
end;
