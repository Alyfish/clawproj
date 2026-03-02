import Foundation
import UserNotifications
import UIKit
import Combine

// MARK: - NotificationManager

final class NotificationManager: NSObject, ObservableObject {

    static let shared = NotificationManager()

    // MARK: Category & Action IDs

    static let approvalCategory = "APPROVAL_NEEDED"
    static let monitoringAlertCategory = "MONITORING_ALERT"
    static let taskCompletedCategory = "TASK_COMPLETED"

    static let approveAction = "APPROVE_ACTION"
    static let denyAction = "DENY_ACTION"

    // MARK: Published state

    @Published private(set) var deviceToken: String?
    @Published private(set) var permissionGranted = false

    // MARK: Dependencies

    weak var webSocket: (any WebSocketServiceProtocol)?

    // MARK: Init

    private override init() {
        super.init()
    }

    // MARK: - Setup

    func setup() {
        registerCategories()
        UNUserNotificationCenter.current().delegate = self
        requestPermission()
    }

    // MARK: - Permission

    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(
            options: [.alert, .badge, .sound]
        ) { [weak self] granted, error in
            DispatchQueue.main.async {
                self?.permissionGranted = granted
            }
            if let error {
                self?.log("permission error: \(error.localizedDescription)")
            }
            if granted {
                DispatchQueue.main.async {
                    UIApplication.shared.registerForRemoteNotifications()
                }
            }
        }
    }

    // MARK: - Categories

    private func registerCategories() {
        let approveAction = UNNotificationAction(
            identifier: Self.approveAction,
            title: "Approve",
            options: [.authenticationRequired]
        )

        let denyAction = UNNotificationAction(
            identifier: Self.denyAction,
            title: "Deny",
            options: [.authenticationRequired, .destructive]
        )

        let approvalCategory = UNNotificationCategory(
            identifier: Self.approvalCategory,
            actions: [approveAction, denyAction],
            intentIdentifiers: [],
            options: []
        )

        let monitoringCategory = UNNotificationCategory(
            identifier: Self.monitoringAlertCategory,
            actions: [],
            intentIdentifiers: [],
            options: []
        )

        let taskCategory = UNNotificationCategory(
            identifier: Self.taskCompletedCategory,
            actions: [],
            intentIdentifiers: [],
            options: []
        )

        UNUserNotificationCenter.current().setNotificationCategories([
            approvalCategory,
            monitoringCategory,
            taskCategory,
        ])
    }

    // MARK: - APNs Token Registration

    func didRegisterForRemoteNotifications(withDeviceToken data: Data) {
        let token = data.map { String(format: "%02.2hhx", $0) }.joined()
        DispatchQueue.main.async {
            self.deviceToken = token
        }
        log("APNs token: \(token)")

        // Send token to gateway
        Task { @MainActor in
            guard let ws = self.webSocket else { return }
            let message = WSMessage.request(
                method: "device.registerPush",
                id: UUID().uuidString,
                payload: [
                    "platform": AnyCodable("ios"),
                    "deviceToken": AnyCodable(token),
                ]
            )
            ws.send(message)
        }
    }

    func didFailToRegisterForRemoteNotifications(withError error: Error) {
        log("APNs registration failed: \(error.localizedDescription)")
    }

    // MARK: - Badge Management

    func updateBadge(count: Int) {
        Task {
            do {
                try await UNUserNotificationCenter.current().setBadgeCount(count)
            } catch {
                log("badge error: \(error.localizedDescription)")
            }
        }
    }

    func clearBadge() {
        updateBadge(count: 0)
    }

    // MARK: - Local Notification Helpers (for testing)

    func sendLocalApprovalNotification(
        approvalId: String,
        title: String,
        body: String
    ) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.categoryIdentifier = Self.approvalCategory
        content.userInfo = ["approvalId": approvalId]

        let request = UNNotificationRequest(
            identifier: "approval-\(approvalId)",
            content: content,
            trigger: nil // deliver immediately
        )

        UNUserNotificationCenter.current().add(request) { [weak self] error in
            if let error {
                self?.log("local approval notification error: \(error.localizedDescription)")
            }
        }
    }

    func sendLocalMonitoringNotification(
        taskId: String,
        title: String,
        body: String
    ) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.categoryIdentifier = Self.monitoringAlertCategory
        content.userInfo = ["taskId": taskId]

        let request = UNNotificationRequest(
            identifier: "monitoring-\(taskId)-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        UNUserNotificationCenter.current().add(request) { [weak self] error in
            if let error {
                self?.log("local monitoring notification error: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Helpers

    private func log(_ message: String) {
        #if DEBUG
        print("[NotificationManager] \(message)")
        #endif
    }
}

// MARK: - UNUserNotificationCenterDelegate

extension NotificationManager: UNUserNotificationCenterDelegate {

    // Tap or action on a notification
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        let categoryId = response.notification.request.content.categoryIdentifier

        switch categoryId {
        case Self.approvalCategory:
            handleApprovalAction(response: response, userInfo: userInfo)
        case Self.monitoringAlertCategory:
            handleMonitoringAction(userInfo: userInfo)
        case Self.taskCompletedCategory:
            handleTaskAction(userInfo: userInfo)
        default:
            break
        }

        completionHandler()
    }

    // Show notification even when app is in foreground
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .badge])
    }

    // MARK: Action Handlers

    private func handleApprovalAction(
        response: UNNotificationResponse,
        userInfo: [AnyHashable: Any]
    ) {
        guard let approvalId = userInfo["approvalId"] as? String else { return }

        switch response.actionIdentifier {
        case Self.approveAction:
            log("quick-action: approve \(approvalId)")
            webSocket?.sendApprovalResponse(approvalId: approvalId, decision: "approved")

        case Self.denyAction:
            log("quick-action: deny \(approvalId)")
            webSocket?.sendApprovalResponse(approvalId: approvalId, decision: "denied")

        case UNNotificationDefaultActionIdentifier:
            // User tapped the notification body — deep link to approval detail
            NotificationCenter.default.post(
                name: .deepLinkToApproval,
                object: nil,
                userInfo: ["approvalId": approvalId]
            )

        default:
            break
        }
    }

    private func handleMonitoringAction(userInfo: [AnyHashable: Any]) {
        guard let taskId = userInfo["taskId"] as? String else { return }
        NotificationCenter.default.post(
            name: .deepLinkToTask,
            object: nil,
            userInfo: ["taskId": taskId]
        )
    }

    private func handleTaskAction(userInfo: [AnyHashable: Any]) {
        guard let taskId = userInfo["taskId"] as? String else { return }
        NotificationCenter.default.post(
            name: .deepLinkToTask,
            object: nil,
            userInfo: ["taskId": taskId]
        )
    }
}

// MARK: - Notification.Name Extensions

extension Notification.Name {
    static let deepLinkToApproval = Notification.Name("deepLinkToApproval")
    static let deepLinkToTask = Notification.Name("deepLinkToTask")
}
