"""Version-independent *plain* launch of the registered, signed Store Codex.

No skin adapter, CDP switch, process termination, or preference mutation is
allowed here. This module is also embedded into the stable shortcut bootstrap
so a missing or outdated pinned skin runtime cannot strand the application.
"""

import base64
import json
import os
import re
import subprocess
from pathlib import Path


class OfficialCodexLaunchError(RuntimeError):
    pass


def official_powershell_path() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) /
               "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def official_powershell_environment() -> dict[str, str]:
    # A PowerShell 7 parent otherwise makes Windows PowerShell import Core-only
    # Security/Appx modules. Only this child gets the Windows inbox module path.
    environment = os.environ.copy()
    for key in list(environment):
        if key.casefold() == "psmodulepath":
            del environment[key]
    environment["PSModulePath"] = str(Path(official_powershell_path()).parent / "Modules")
    return environment


def official_config_locale() -> str | None:
    path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    try:
        content = path.read_text(encoding="utf-8")
        try:
            import tomllib
            value = tomllib.loads(content).get("desktop", {}).get("localeOverride")
        except ImportError:
            section = re.search(r"(?ms)^\[desktop\]\s*\n(.*?)(?=^\[|\Z)", content)
            match = re.search(r"(?m)^localeOverride\s*=\s*['\"]([A-Za-z0-9_-]+)['\"]\s*(?:#.*)?$",
                              section.group(1)) if section else None
            value = match.group(1) if match else None
        return _official_locale(value)
    except (OSError, ValueError, AttributeError, OfficialCodexLaunchError):
        return None


def _official_locale(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise OfficialCodexLaunchError("invalid ordinary Codex locale")
    value = value.replace("_", "-")
    if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise OfficialCodexLaunchError("invalid ordinary Codex locale")
    return value


_OFFICIAL_CODEX_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$family = 'OpenAI.Codex_2p2nqsd0c76g0'
$packages = @(Get-AppxPackage -Name OpenAI.Codex -ErrorAction Stop | Where-Object {
    $_.PackageFamilyName -ceq $family -and -not $_.IsResourcePackage -and -not $_.IsBundle
})
if ($packages.Count -ne 1) { throw 'No unique registered official Codex Store package' }
$package = $packages[0]
if ([string]$package.SignatureKind -ne 'Store' -or [string]$package.Status -ne 'Ok' -or
    $package.IsDevelopmentMode -or $package.Publisher -cne 'CN=50BDFD77-8903-4850-9FFE-6E8522F64D5B') {
    throw 'Official Codex package identity or Store signature did not pass'
}
$manifest = Get-AppxPackageManifest -Package $package -ErrorAction Stop
$apps = @($manifest.Package.Applications.Application | Where-Object { $_.Id -ceq 'App' })
if ($apps.Count -ne 1 -or $apps[0].Executable.Replace('/', '\') -cne 'app\ChatGPT.exe') {
    throw 'Official Codex manifest application target did not pass'
}
$executable = [IO.Path]::GetFullPath((Join-Path $package.InstallLocation 'app\ChatGPT.exe'))
$item = Get-Item -LiteralPath $executable -ErrorAction Stop
$signature = Get-AuthenticodeSignature -LiteralPath $executable
if ([string]$signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
    $signature.SignerCertificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) -cne 'OpenAI OpCo, LLC' -or
    $item.VersionInfo.ProductName -cne 'Codex' -or $item.VersionInfo.CompanyName -cne 'OpenAI OpCo, LLC') {
    throw 'Official Codex executable signature or product identity did not pass'
}
$result = [ordered]@{
    mode = 'plain-official-appx'; skinApplied = $false; launched = $false
    executable = $executable; appVersion = [string]$package.Version
    packageFamilyName = $family; signatureStatus = [string]$signature.Status
    appUserModelId = "$family!App"; locale = $env:CHROMAPAW_OFFICIAL_LOCALE
}
if ($env:CHROMAPAW_OFFICIAL_LAUNCH -eq '1') {
    $source = @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IChromaPawOfficialActivationManager {
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string id, [MarshalAs(UnmanagedType.LPWStr)] string args, uint options, out uint pid);
    [PreserveSig] int ActivateForFile(IntPtr id, IntPtr items, IntPtr verb, out uint pid);
    [PreserveSig] int ActivateForProtocol(IntPtr id, IntPtr items, out uint pid);
}
[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
class ChromaPawOfficialActivationManager {}
public static class ChromaPawOfficialActivation {
    public static uint Launch(string id, string args) {
        var manager = (IChromaPawOfficialActivationManager)new ChromaPawOfficialActivationManager();
        uint pid;
        int hr = manager.ActivateApplication(id, args, 0, out pid);
        if (hr < 0) Marshal.ThrowExceptionForHR(hr);
        return pid;
    }
}
'@
    Add-Type -TypeDefinition $source -Language CSharp
    $arguments = ''
    if ($env:CHROMAPAW_OFFICIAL_LOCALE) { $arguments = '--lang=' + $env:CHROMAPAW_OFFICIAL_LOCALE }
    $activatedPid = [ChromaPawOfficialActivation]::Launch("$family!App", $arguments)
    $actual = (Get-Process -Id $activatedPid -ErrorAction Stop).Path
    if (-not $actual -or [IO.Path]::GetFullPath($actual) -ine $executable) {
        throw 'Official activation returned an unexpected process; no process was terminated'
    }
    $result.launched = $true
    $result.pid = [int64]$activatedPid
}
$result | ConvertTo-Json -Compress
'''


def _run_official_codex(*, launch: bool, locale: str | None = None) -> dict[str, object]:
    if os.name != "nt":
        raise OfficialCodexLaunchError("ordinary Store Codex launch is Windows-only")
    environment = official_powershell_environment()
    environment["CHROMAPAW_OFFICIAL_LAUNCH"] = "1" if launch else "0"
    environment["CHROMAPAW_OFFICIAL_LOCALE"] = _official_locale(locale) or ""
    encoded = base64.b64encode(_OFFICIAL_CODEX_SCRIPT.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [official_powershell_path(), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=environment,
        )
        if completed.returncode != 0:
            raise OfficialCodexLaunchError(completed.stderr.strip() or "official Codex probe failed")
        result = json.loads(completed.stdout)
        if (not isinstance(result, dict) or result.get("skinApplied") is not False
                or result.get("packageFamilyName") != "OpenAI.Codex_2p2nqsd0c76g0"
                or result.get("signatureStatus") != "Valid"):
            raise OfficialCodexLaunchError("invalid official Codex launch result")
        if launch and (result.get("launched") is not True or not isinstance(result.get("pid"), int)):
            raise OfficialCodexLaunchError("official Codex did not report a verified process")
        return result
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise OfficialCodexLaunchError(f"official Codex launch failed: {exc}") from exc


def probe_current_official_codex() -> dict[str, object]:
    return _run_official_codex(launch=False)


def launch_current_official_codex(locale: str | None = None) -> dict[str, object]:
    return _run_official_codex(launch=True, locale=locale)
