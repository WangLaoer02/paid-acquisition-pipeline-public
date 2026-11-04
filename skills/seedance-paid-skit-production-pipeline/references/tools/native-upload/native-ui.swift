import Foundation
import AppKit
import ApplicationServices

// Native accessibility only: no page JavaScript, cookies, or credentials.
func attr(_ e: AXUIElement, _ key: String) -> CFTypeRef? {
    var out: CFTypeRef?
    guard AXUIElementCopyAttributeValue(e, key as CFString, &out) == .success else { return nil }
    return out
}
func string(_ e: AXUIElement, _ key: String) -> String {
    return attr(e, key) as? String ?? ""
}
func children(_ e: AXUIElement) -> [AXUIElement] {
    return attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? []
}
let args = Array(CommandLine.arguments.dropFirst())
guard ProcessInfo.processInfo.environment["WORKFLOW_NATIVE_CONTROLLER_PID"] == String(getppid()) else { print("GUARDED_CONTROLLER_REQUIRED"); exit(9) }
guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.google.Chrome").first else {
    print("{\"error\":\"CHROME_NOT_RUNNING\"}"); exit(1)
}
guard AXIsProcessTrusted() else {
    print("{\"error\":\"NATIVE_ACCESSIBILITY_UNAVAILABLE\"}"); exit(1)
}
let applicationAX = AXUIElementCreateApplication(app.processIdentifier)
let expectedWindow = ProcessInfo.processInfo.environment["WORKFLOW_NATIVE_WINDOW_TITLE"] ?? ""
let windows = children(applicationAX).filter { string($0,kAXRoleAttribute) == "AXWindow" && string($0,kAXTitleAttribute) == expectedWindow }
guard !expectedWindow.isEmpty, windows.count == 1 else { print("{\"error\":\"NATIVE_WINDOW_NOT_UNIQUE\"}"); exit(14) }
let targetWindow = windows[0]
if !args.isEmpty { app.activate(options: []); AXUIElementPerformAction(targetWindow,kAXRaiseAction as CFString) }
if args.first == "goto" {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
    task.arguments = ["-e", "tell application \"System Events\" to key code 5 using {command down, shift down}"]
    try task.run(); task.waitUntilExit()
    guard task.terminationStatus == 0 else { exit(11) }
    print("{\"ok\":true,\"key\":\"CmdShiftG\"}"); exit(0)
}
let root = targetWindow
AXUIElementSetMessagingTimeout(root, 3)
var rows: [[String: Any]] = []
var elements: [String: AXUIElement] = [:]
func walk(_ e: AXUIElement, _ path: String, _ depth: Int) {
    if depth > 40 || rows.count > 6000 { return }
    let role = string(e, kAXRoleAttribute)
    let title = string(e, kAXTitleAttribute)
    let desc = string(e, kAXDescriptionAttribute)
    let subrole = string(e, kAXSubroleAttribute)
    if title == "DevTools" { return }
    elements[path] = e
    let roles = ["AXWebArea", "AXButton", "AXPopUpButton", "AXComboBox", "AXLink", "AXStaticText", "AXRadioButton", "AXCheckBox", "AXTextField", "AXMenuItem", "AXList", "AXRow", "AXHeading", "AXSheet"]
    var actionNames: CFArray?
    AXUIElementCopyActionNames(e, &actionNames)
    let actions = actionNames as? [String] ?? []
    if roles.contains(role) || !actions.isEmpty {
        var row: [String: Any] = ["path": path, "role": role, "title": title, "description": desc]
        let identifier = string(e,"AXDOMIdentifier")
        if !identifier.isEmpty { row["dom_id"] = identifier }
        if !actions.isEmpty { row["actions"] = actions }
        if subrole != "AXSecureTextField" {
            if let v = attr(e, kAXValueAttribute) as? String { row["value"] = v }
            else if let v = attr(e, kAXValueAttribute) as? NSNumber { row["value"] = v }
        }
        var point = CGPoint.zero
        if let v = attr(e, kAXPositionAttribute), CFGetTypeID(v) == AXValueGetTypeID() {
            AXValueGetValue(v as! AXValue, .cgPoint, &point)
            row["position"] = [point.x, point.y]
        }
        rows.append(row)
    }
    for (i, child) in children(e).enumerated() { walk(child, path + "." + String(i), depth + 1) }
}
walk(root, "0", 0)
if ["press", "click", "set", "select"].contains(args.first ?? ""), args.count >= 2 {
    guard let e = elements[args[1]] else { print("{\"error\":\"ELEMENT_NOT_FOUND\"}"); exit(2) }
    let title = string(e, kAXTitleAttribute)
    
    if args[0] == "select" {
        let cellPath = args[1].components(separatedBy: ".").dropLast().joined(separator: ".")
        let listPath = args[1].components(separatedBy: ".").dropLast(2).joined(separator: ".")
        guard string(e,kAXRoleAttribute) == "AXTextField", string(e,kAXValueAttribute).hasSuffix(".mp4"), let cell = elements[cellPath], let list = elements[listPath], string(list,kAXRoleAttribute) == "AXList" else { exit(13) }
        var settable = DarwinBoolean(false)
        AXUIElementIsAttributeSettable(list, kAXSelectedChildrenAttribute as CFString, &settable)
        var result = AXError.attributeUnsupported
        if settable.boolValue { result = AXUIElementSetAttributeValue(list,kAXSelectedChildrenAttribute as CFString,[cell] as CFArray) }
        else {
            AXUIElementIsAttributeSettable(cell,kAXSelectedAttribute as CFString,&settable)
            if settable.boolValue { result = AXUIElementSetAttributeValue(cell,kAXSelectedAttribute as CFString,kCFBooleanTrue) }
        }
        print("{\"native_action\":\"select_file_row\",\"settable\":\(settable.boolValue),\"result\":\(result.rawValue)}")
        exit(result == .success ? 0 : 3)
    }
    var result = AXError.success
    if args[0] == "set", args.count == 3 {
        guard ["AXTextField","AXTextArea","AXComboBox"].contains(string(e,kAXRoleAttribute)), string(e,kAXSubroleAttribute) != "AXSecureTextField" else { exit(5) }
        result = AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,args[2] as CFString)

    } else if args[0] == "click" {
        var point = CGPoint.zero
        var size = CGSize.zero
        guard let p = attr(e,kAXPositionAttribute), let s = attr(e,kAXSizeAttribute) else { exit(6) }
        AXValueGetValue(p as! AXValue,.cgPoint,&point)
        AXValueGetValue(s as! AXValue,.cgSize,&size)
        let center = CGPoint(x:point.x + size.width/2,y:point.y + size.height/2)
        guard center.y > 0 && center.y < 1000 && center.x > 0 && center.x < 1920 else { exit(7) }
        CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:center,mouseButton:.left)?.post(tap:.cghidEventTap)
        CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:center,mouseButton:.left)?.post(tap:.cghidEventTap)
    } else {
        result = AXUIElementPerformAction(e, kAXPressAction as CFString)
    }
    let obj: [String: Any] = ["action": args[0], "path": args[1], "role": string(e,kAXRoleAttribute), "title":title, "result":result.rawValue]
    let data = try JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
    print(String(data:data,encoding:.utf8)!); exit(result == .success ? 0 : 3)
}
let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
