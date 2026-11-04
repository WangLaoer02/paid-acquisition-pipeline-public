import Foundation
import Security

// Separate session items; never read or modify the existing account/password item.
let service = "com.codex.rongyao-http-session"
let args = Array(CommandLine.arguments.dropFirst())
func emit(_ value: [String: Any], _ code: Int32 = 0) -> Never {
    FileHandle.standardOutput.write(try! JSONSerialization.data(withJSONObject: value))
    FileHandle.standardOutput.write(Data("\n".utf8)); exit(code)
}
func fail(_ status: String, _ code: OSStatus? = nil) -> Never {
    var value: [String: Any] = ["ok": false, "status": status]
    if let code = code { value["os_status"] = code }
    emit(value, 1)
}
guard args.count == 2, ["status", "load", "save", "clear"].contains(args[0]),
      ["readonly", "upload"].contains(args[1]) else { fail("INVALID_SESSION_VAULT_COMMAND") }
let command = args[0], scope = args[1]
var query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: service, kSecAttrAccount as String: scope,
    kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail]
if command == "clear" {
    let status = SecItemDelete(query as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { fail("SESSION_VAULT_ACCESS_REQUIRED", status) }
    emit(["ok": true, "status": "SESSION_FORGOTTEN", "scope": scope])
}
if command == "save" {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 524288,
          let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          value["version"] as? Int == 1, value["scope"] as? String == scope,
          value["cookies"] is [[String: Any]] else { fail("INVALID_SESSION_PAYLOAD") }
    let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
    if status == errSecItemNotFound {
        var trusted: SecTrustedApplication?
        let path = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL.path
        var result = SecTrustedApplicationCreateFromPath(path, &trusted)
        guard result == errSecSuccess, let trusted = trusted else { fail("SESSION_VAULT_TRUST_SETUP_FAILED", result) }
        var access: SecAccess?
        result = SecAccessCreate("荣耀HTTP可恢复会话" as CFString, [trusted] as CFArray, &access)
        guard result == errSecSuccess, let access = access else { fail("SESSION_VAULT_TRUST_SETUP_FAILED", result) }
        var add = query; add.removeValue(forKey: kSecUseAuthenticationUI as String)
        add[kSecValueData as String] = data
        add[kSecAttrLabel as String] = "荣耀HTTP会话 · " + scope
        add[kSecAttrAccess as String] = access
        add[kSecAttrSynchronizable as String] = false
        result = SecItemAdd(add as CFDictionary, nil)
        guard result == errSecSuccess else { fail("SESSION_VAULT_ACCESS_REQUIRED", result) }
    } else if status != errSecSuccess { fail("SESSION_VAULT_ACCESS_REQUIRED", status) }
    emit(["ok": true, "status": "SESSION_SAVED", "scope": scope, "secret_returned": false])
}
query[command == "load" ? kSecReturnData as String : kSecReturnAttributes as String] = true
var item: CFTypeRef?
let status = SecItemCopyMatching(query as CFDictionary, &item)
if status == errSecItemNotFound { emit(["ok": true, "status": "NO_SAVED_SESSION", "scope": scope]) }
guard status == errSecSuccess else { fail("SESSION_VAULT_ACCESS_REQUIRED", status) }
if command == "status" { emit(["ok": true, "status": "SAVED_SESSION_PRESENT", "scope": scope, "secret_returned": false]) }
guard let data = item as? Data else { fail("INVALID_SESSION_PAYLOAD") }
// Only the fixed Python consumer captures this private pipe. Never expose load via a CLI.
FileHandle.standardOutput.write(data)
