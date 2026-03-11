import Foundation
import Combine

@MainActor
final class TaskFeedViewModel: ObservableObject {

    // MARK: - Published state

    @Published var tasks: [AgentTask] = []
    @Published var watchItems: [WatchlistItem] = []
    @Published var alerts: [WatchlistAlert] = []
    @Published var bannerAlert: WatchlistAlert?
    @Published var pendingApprovals: [PendingApproval] = []
    @Published var selectedTask: AgentTask?
    @Published var selectedWatchItem: WatchlistItem?

    // MARK: - Computed

    var alertBadgeCount: Int { alerts.filter { !$0.isRead }.count }

    // MARK: - Private

    private let webSocket: any WebSocketServiceProtocol
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Init

    init(webSocket: any WebSocketServiceProtocol) {
        self.webSocket = webSocket

        webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleEvent(event)
            }
            .store(in: &cancellables)
    }

    // MARK: - Public actions

    func refresh() async {
        // Tasks come from real-time gateway events.
        // TODO: Request task list from gateway on pull-to-refresh.
    }

    func stopTask(_ taskId: String) {
        webSocket.sendTaskStop(taskId: taskId)
        // Optimistic update
        if let index = tasks.firstIndex(where: { $0.id == taskId }) {
            tasks[index].status = .stopped
            tasks[index].updatedAt = ISO8601DateFormatter().string(from: Date())
        }
    }

    func toggleWatchActive(_ item: WatchlistItem, active: Bool) {
        let method = active ? "schedule.resume" : "schedule.pause"
        let payload: [String: AnyCodable] = [
            "watchId": AnyCodable(item.id),
        ]
        let message = WSMessage.request(
            method: method,
            id: UUID().uuidString,
            payload: payload
        )
        webSocket.send(message)
        // Optimistic update
        if let index = watchItems.firstIndex(where: { $0.id == item.id }) {
            var updated = watchItems[index]
            updated.active = active
            watchItems[index] = updated
        }
    }

    func approveAction(_ approvalId: String) {
        webSocket.sendApprovalResponse(approvalId: approvalId, decision: "approved")
        pendingApprovals.removeAll { $0.id == approvalId }
    }

    func denyAction(_ approvalId: String) {
        webSocket.sendApprovalResponse(approvalId: approvalId, decision: "denied")
        pendingApprovals.removeAll { $0.id == approvalId }
    }

    // MARK: - Event handling

    private func handleEvent(_ event: StreamEvent) {
        switch event {
        case .taskUpdate(let taskId, let status, let step):
            if let index = tasks.firstIndex(where: { $0.id == taskId }) {
                // Update existing task
                if let newStatus = TaskStatus(rawValue: status) {
                    tasks[index].status = newStatus
                }
                if let step {
                    if let stepIndex = tasks[index].steps.firstIndex(where: { $0.id == step.id }) {
                        tasks[index].steps[stepIndex] = step
                    } else {
                        tasks[index].steps.append(step)
                    }
                }
                tasks[index].updatedAt = ISO8601DateFormatter().string(from: Date())
            } else {
                // Create new task on first event
                let now = ISO8601DateFormatter().string(from: Date())
                let newTask = AgentTask(
                    id: taskId,
                    status: TaskStatus(rawValue: status) ?? .executing,
                    goal: step?.description ?? "Processing...",
                    steps: step.map { [$0] } ?? [],
                    cardIds: [],
                    approvalIds: [],
                    createdAt: now,
                    updatedAt: now
                )
                tasks.insert(newTask, at: 0)
            }

        case .approvalRequested(let id, let taskId, let action, let description, _):
            guard !pendingApprovals.contains(where: { $0.id == id }) else { return }
            let approval = PendingApproval(
                id: id,
                taskId: taskId,
                action: action,
                description: description,
                createdAt: ISO8601DateFormatter().string(from: Date())
            )
            pendingApprovals.append(approval)

        case .watchUpdate(let action, let watchData, let alertData):
            switch action {
            case "created", "updated", "resumed":
                if let watchData = watchData,
                   let id = watchData["id"]?.value as? String,
                   let desc = watchData["description"]?.value as? String {
                    let typeStr = watchData["type"]?.value as? String ?? "price_watch"
                    let taskId = watchData["taskId"]?.value as? String ?? ""
                    let filtersAny = watchData["filters"]?.value as? [String: Any] ?? [:]
                    let filters = filtersAny.compactMapValues { $0 as? String }
                    let interval = watchData["interval"]?.value as? String ?? "every_6_hours"
                    let lastChecked = watchData["lastChecked"]?.value as? String
                    let active = watchData["active"]?.value as? Bool ?? true
                    let item = WatchlistItem(
                        id: id,
                        taskId: taskId,
                        type: WatchlistType(rawValue: typeStr) ?? .priceWatch,
                        description: desc,
                        filters: filters,
                        interval: interval,
                        lastChecked: lastChecked,
                        active: active
                    )
                    if let idx = watchItems.firstIndex(where: { $0.id == id }) {
                        watchItems[idx] = item
                    } else {
                        watchItems.append(item)
                    }
                }
            case "removed":
                if let watchData = watchData,
                   let id = watchData["id"]?.value as? String {
                    watchItems.removeAll { $0.id == id }
                }
            case "paused":
                if let watchData = watchData,
                   let id = watchData["id"]?.value as? String,
                   let idx = watchItems.firstIndex(where: { $0.id == id }) {
                    // Create updated item with active=false
                    var updated = watchItems[idx]
                    updated.active = false
                    watchItems[idx] = updated
                }
            case "alert":
                let watchId = watchData?["id"]?.value as? String ?? ""
                let watchDesc = watchData?["description"]?.value as? String ?? ""
                let skillName = alertData?["type"]?.value as? String
                    ?? watchData?["type"]?.value as? String ?? ""
                let dataDict = alertData?["data"]?.value as? [String: Any] ?? [:]
                let timestamp = alertData?["timestamp"]?.value as? String
                    ?? ISO8601DateFormatter().string(from: Date())

                let alert = WatchlistAlert(
                    id: UUID().uuidString,
                    watchId: watchId,
                    alertType: Self.inferAlertType(skillName: skillName, data: dataDict),
                    title: watchDesc,
                    message: Self.buildAlertMessage(skillName: skillName, data: dataDict, fallback: watchDesc),
                    source: skillName,
                    previousValue: Self.extractValue(from: dataDict, keys: ["previousPrice", "oldPrice", "oldSpread", "previousValue"]),
                    currentValue: Self.extractValue(from: dataDict, keys: ["currentPrice", "newPrice", "price", "newSpread", "currentValue", "rent"]),
                    url: dataDict["url"] as? String,
                    cardType: Self.inferCardType(skillName: skillName),
                    timestamp: timestamp
                )
                alerts.insert(alert, at: 0)
                if alerts.count > 100 { alerts = Array(alerts.prefix(100)) }

                // Show in-app banner
                bannerAlert = alert

                // Fire local notification
                NotificationManager.shared.sendLocalMonitoringNotification(
                    taskId: watchId, title: alert.title, body: alert.message
                )
            default:
                break
            }

        case .watchlistAlert(let alert):
            alerts.insert(alert, at: 0)
            if alerts.count > 100 { alerts = Array(alerts.prefix(100)) }
            bannerAlert = alert
            NotificationManager.shared.sendLocalMonitoringNotification(
                taskId: alert.watchId, title: alert.title, body: alert.message
            )

        default:
            break
        }
    }

    // MARK: - Alert actions

    func markAsRead(_ identifier: String) {
        if let i = alerts.firstIndex(where: { $0.id == identifier || $0.watchId == identifier }) {
            alerts[i].isRead = true
            webSocket.markWatchlistAlertsRead(alertIds: [alerts[i].id])
        }
    }

    func markAllAsRead() {
        for i in alerts.indices {
            alerts[i].isRead = true
        }
        webSocket.markAllWatchlistAlertsRead()
    }

    func dismissBanner() {
        bannerAlert = nil
    }

    // MARK: - Alert parsing helpers

    private static func inferAlertType(skillName: String, data: [String: Any]) -> String {
        switch skillName {
        case "price_monitor", "flight_search":
            // Check if price went up or down
            if let prev = data["previousPrice"] ?? data["oldPrice"],
               let curr = data["currentPrice"] ?? data["newPrice"] ?? data["price"],
               let prevNum = Double("\(prev)"), let currNum = Double("\(curr)") {
                return currNum < prevNum ? "price_drop" : "price_increase"
            }
            return "price_drop"
        case "apartment_search":
            return "new_listing"
        case "betting_odds":
            return "line_movement"
        default:
            return "price_drop"
        }
    }

    private static func buildAlertMessage(skillName: String, data: [String: Any], fallback: String) -> String {
        switch skillName {
        case "price_monitor", "flight_search":
            if let price = data["currentPrice"] ?? data["newPrice"] ?? data["price"],
               let airline = data["airline"] {
                return "Price dropped to $\(price) on \(airline)"
            }
            if let price = data["currentPrice"] ?? data["newPrice"] ?? data["price"] {
                return "Price changed to $\(price)"
            }
        case "apartment_search":
            if let address = data["address"], let rent = data["rent"] {
                return "New listing at \(address) for $\(rent)/mo"
            }
        case "betting_odds":
            if let oldSpread = data["oldSpread"], let newSpread = data["newSpread"],
               let team = data["team"] {
                return "\(team) spread moved from \(oldSpread) to \(newSpread)"
            }
        default:
            break
        }
        // Fallback: use first meaningful value from data or watch description
        if let firstValue = data.first(where: { $0.key != "timestamp" }) {
            return "\(firstValue.key): \(firstValue.value)"
        }
        return fallback.isEmpty ? "Change detected" : fallback
    }

    private static func inferCardType(skillName: String) -> String? {
        switch skillName {
        case "price_monitor", "flight_search": return "flight"
        case "apartment_search": return "house"
        case "betting_odds": return "pick"
        default: return nil
        }
    }

    private static func extractValue(from data: [String: Any], keys: [String]) -> String? {
        for key in keys {
            if let value = data[key] {
                return "\(value)"
            }
        }
        return nil
    }

    // MARK: - Mock data

    private func loadMockData() {
        tasks = [.mock, .mockSearching, .mockAwaitingApproval, .mockStopped]
        watchItems = [.mockPriceWatch, .mockNewListing, .mockLineMovement]
        alerts = [.mockPriceDrop, .mockNewApt, .mockLineAlert]
        pendingApprovals = [.mock]
    }
}
