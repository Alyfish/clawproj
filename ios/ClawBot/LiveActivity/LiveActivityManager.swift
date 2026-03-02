import ActivityKit
import Foundation

// MARK: - LiveActivityManager

/// Manages the lifecycle of ClawBot Live Activities (lock screen + Dynamic Island).
/// Singleton — wire `webSocket` after the service connects.
@MainActor
final class LiveActivityManager: ObservableObject {

    static let shared = LiveActivityManager()

    // MARK: Published state

    @Published private(set) var activeActivities: [String: Activity<ClawBotActivityAttributes>] = [:]

    // MARK: Dependencies

    weak var webSocket: (any WebSocketServiceProtocol)?

    // MARK: Init

    private init() {}

    // MARK: - Query Helpers

    var activeCount: Int { activeActivities.count }

    func isActive(taskId: String) -> Bool {
        activeActivities[taskId] != nil
    }

    // MARK: - Start Activity

    func startActivity(taskId: String, goal: String, totalSteps: Int) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            log("Live Activities not enabled")
            return
        }

        guard activeActivities[taskId] == nil else {
            log("activity already exists for task \(taskId)")
            return
        }

        let attributes = ClawBotActivityAttributes(taskId: taskId, goalText: goal)
        let initialState = ClawBotActivityAttributes.ContentState(
            status: "running",
            currentStep: "Starting...",
            stepCount: 0,
            totalSteps: totalSteps
        )

        let content = ActivityContent(state: initialState, staleDate: nil)

        do {
            let activity = try Activity.request(
                attributes: attributes,
                content: content,
                pushType: .token
            )
            activeActivities[taskId] = activity
            log("started activity for task \(taskId), id: \(activity.id)")

            // Observe push token updates in background
            Task { [weak self] in
                await self?.observePushTokenUpdates(for: activity, taskId: taskId)
            }
        } catch {
            log("failed to start activity: \(error.localizedDescription)")
        }
    }

    // MARK: - Update Activity

    func updateActivity(taskId: String, status: String, currentStep: String, stepCount: Int) {
        guard let activity = activeActivities[taskId] else {
            log("no active activity for task \(taskId)")
            return
        }

        let totalSteps = activity.content.state.totalSteps
        let updatedState = ClawBotActivityAttributes.ContentState(
            status: status,
            currentStep: currentStep,
            stepCount: stepCount,
            totalSteps: totalSteps
        )

        let content = ActivityContent(state: updatedState, staleDate: nil)

        Task {
            await activity.update(content)
            log("updated activity for task \(taskId): step \(stepCount)/\(totalSteps)")
        }
    }

    // MARK: - End Activity

    func endActivity(taskId: String, finalStatus: String) {
        guard let activity = activeActivities[taskId] else {
            log("no active activity for task \(taskId)")
            return
        }

        let finalState = ClawBotActivityAttributes.ContentState(
            status: finalStatus,
            currentStep: finalStatus == "completed" ? "Done" : "Stopped",
            stepCount: activity.content.state.stepCount,
            totalSteps: activity.content.state.totalSteps
        )

        let content = ActivityContent(state: finalState, staleDate: nil)

        Task {
            await activity.end(content, dismissalPolicy: .after(.now + 300)) // 5 min
            log("ended activity for task \(taskId) with status \(finalStatus)")
        }

        activeActivities.removeValue(forKey: taskId)
    }

    // MARK: - End All

    func endAll() {
        for taskId in activeActivities.keys {
            endActivity(taskId: taskId, finalStatus: "stopped")
        }
    }

    // MARK: - Push Token Observation

    private func observePushTokenUpdates(
        for activity: Activity<ClawBotActivityAttributes>,
        taskId: String
    ) async {
        for await tokenData in activity.pushTokenUpdates {
            let token = tokenData.map { String(format: "%02x", $0) }.joined()
            log("push token for task \(taskId): \(token)")
            await MainActor.run {
                self.sendPushTokenToGateway(taskId: taskId, token: token)
            }
        }
    }

    // MARK: - Gateway Communication

    /// Sends the Live Activity push token to the gateway. Synchronous `ws.send()`.
    private func sendPushTokenToGateway(taskId: String, token: String) {
        guard let ws = webSocket else {
            log("no webSocket — cannot send push token")
            return
        }

        let message = WSMessage.request(
            method: "device.registerActivityToken",
            id: UUID().uuidString,
            payload: [
                "taskId": AnyCodable(taskId),
                "pushToken": AnyCodable(token),
                "platform": AnyCodable("ios"),
            ]
        )
        ws.send(message)
    }

    // MARK: - Helpers

    private func log(_ message: String) {
        #if DEBUG
        print("[LiveActivityManager] \(message)")
        #endif
    }
}
