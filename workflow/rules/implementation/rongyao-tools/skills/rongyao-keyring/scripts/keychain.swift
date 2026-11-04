import Foundation
import Security

// Fixed item and fixed workers. Never print or accept credentials on argv.
let home = FileManager.default.homeDirectoryForCurrentUser
let root = home.appendingPathComponent(".codex/skills/rongyao-keyring")
let state = home.appendingPathComponent(".codex/state/rongyao-keyring")
let legacy = home.appendingPathComponent(".codex/state/rongyao-active-session/login.json")
let service = "com.codex.rongyao-keyring"
let account = "existing-rongyao-account"
let disabled = state.appendingPathComponent("disabled")

func emit(_ value: [String: Any], _ code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(code)
}
func failure(_ value: String, _ status: OSStatus? = nil) -> Never {
    var result: [String: Any] = ["ok": false, "status": value]
    if let status = status { result["os_status"] = status }
    emit(result, 1)
}
func query() -> [String: Any] {
    return [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: account,
            kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail]
}
func credentials() -> [String: String] {
    var q = query(); q[kSecReturnData as String] = true
    var item: CFTypeRef?
    let status = SecItemCopyMatching(q as CFDictionary, &item)
    guard status == errSecSuccess, let data = item as? Data else {
        failure(status == errSecItemNotFound ? "CREDENTIALS_NOT_CONFIGURED" : "KEYCHAIN_ACCESS_REQUIRED", status)
    }
    guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: String],
          let user = value["username"], !user.isEmpty,
          let password = value["password"], !password.isEmpty else { failure("CREDENTIALS_INVALID") }
    return ["username": user, "password": password]
}
let args = Array(CommandLine.arguments.dropFirst())
let command = args.first ?? "status"
if command == "disable" {
    try FileManager.default.createDirectory(at: state, withIntermediateDirectories: true,
                                         attributes: [.posixPermissions: 0o700])
    try Data("disabled by owner\n".utf8).write(to: disabled)
    emit(["ok": true, "status": "DISABLED"])
}
if FileManager.default.fileExists(atPath: disabled.path) { failure("ACCESS_REVOKED") }

if command == "status" {
    var q = query(); q[kSecReturnAttributes as String] = true
    var item: CFTypeRef?
    let status = SecItemCopyMatching(q as CFDictionary, &item)
    emit(["ok": status == errSecSuccess, "status": status == errSecSuccess ? "CONFIGURED" : "NOT_READY",
          "os_status": status, "provider": "macos-keychain", "secret_returned": false,
          "legacy_file_exists": FileManager.default.fileExists(atPath: legacy.path)])
}
if command == "import-existing" {
    var q = query(); q[kSecReturnAttributes as String] = true
    var found: CFTypeRef?
    let existing = SecItemCopyMatching(q as CFDictionary, &found)
    if existing == errSecSuccess { emit(["ok": true, "status": "ALREADY_CONFIGURED", "overwritten": false]) }
    guard existing == errSecItemNotFound else { failure("KEYCHAIN_ACCESS_REQUIRED", existing) }
    let attrs = try FileManager.default.attributesOfItem(atPath: legacy.path)
    guard attrs[.type] as? FileAttributeType == .typeRegular,
          let perms = attrs[.posixPermissions] as? NSNumber, perms.intValue & 0o077 == 0 else {
        failure("LEGACY_FILE_PERMISSIONS")
    }
    let data = try Data(contentsOf: legacy)
    guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: String],
          let user = value["username"], !user.isEmpty,
          let password = value["password"], !password.isEmpty else { failure("CREDENTIALS_INVALID") }
    var trusted: SecTrustedApplication?
    let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL.path
    var status = SecTrustedApplicationCreateFromPath(executable, &trusted)
    guard status == errSecSuccess, let trusted = trusted else { failure("TRUSTED_HELPER_FAILED", status) }
    var access: SecAccess?
    status = SecAccessCreate("荣耀钥匙包" as CFString, [trusted] as CFArray, &access)
    guard status == errSecSuccess, let access = access else { failure("KEYCHAIN_ACCESS_SETUP_FAILED", status) }
    var add = query(); add.removeValue(forKey: kSecUseAuthenticationUI as String)
    add[kSecValueData as String] = try JSONSerialization.data(withJSONObject: ["username": user, "password": password])
    add[kSecAttrLabel as String] = "荣耀钥匙包 · 现有账号"
    add[kSecAttrAccess as String] = access
    add[kSecAttrSynchronizable as String] = false
    status = SecItemAdd(add as CFDictionary, nil)
    guard status == errSecSuccess else { failure("KEYCHAIN_IMPORT_FAILED", status) }
    _ = credentials() // Verify retrieval through this same narrow helper.
    emit(["ok": true, "status": "IMPORTED_AND_READBACK_VERIFIED", "provider": "macos-keychain",
          "secret_returned": false, "legacy_file_preserved": true])
}
let modes: Set<String> = ["ensure-query", "verify-upload-chrome", "fast-video", "check-credentials"]
guard modes.contains(command) else { failure("INVALID_COMMAND") }
if command == "fast-video" {
    guard args.count > 1, ["search", "resolve", "frames", "status"].contains(args[1]) else { failure("INVALID_VIDEO_COMMAND") }
}
let secrets = credentials()
if command == "check-credentials" { emit(["ok": true, "status": "CREDENTIAL_READ_VERIFIED", "secret_returned": false]) }
let process = Process()
let python = "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
process.executableURL = URL(fileURLWithPath: FileManager.default.isExecutableFile(atPath: python) ? python : "/usr/bin/python3")
process.arguments = [root.appendingPathComponent("scripts/worker.py").path] + args
var environment = ProcessInfo.processInfo.environment
environment["RONGYAO_USERNAME"] = secrets["username"]
environment["RONGYAO_PASSWORD"] = secrets["password"]
environment.removeValue(forKey: "PYTHONPATH")
process.environment = environment
let pipe = Pipe(); process.standardOutput = pipe
process.standardError = FileHandle.nullDevice
try process.run()
let data = pipe.fileHandleForReading.readDataToEndOfFile()
process.waitUntilExit()
// Workers return JSON, never browser source, exception traces, or credentials.
guard var text = String(data: data, encoding: .utf8) else { failure("WORKER_OUTPUT_INVALID") }
for value in secrets.values { text = text.replacingOccurrences(of: value, with: "[redacted]") }
guard let clean = text.data(using: .utf8), (try? JSONSerialization.jsonObject(with: clean)) != nil else {
    failure("WORKER_OUTPUT_INVALID")
}
FileHandle.standardOutput.write(clean)
exit(process.terminationStatus)
