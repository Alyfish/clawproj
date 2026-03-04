import Foundation
import Combine

@MainActor
final class TaskFeedViewModel: ObservableObject {

    // MARK: - Published state

    @Published var tasks: [AgentTask] = []
    @Published var watchItems: [WatchlistItem] = []
    @Published var alerts: [MonitoringAlert] = []
    @Published var pendingApprovals: [PendingApproval] = []
    @Published var selectedTask: AgentTask?
    @Published var selectedWatchItem: WatchlistItem?

    // MARK: - Computed

    var alertBadgeCount: Int { alerts.count }

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
                if let alertData = alertData,
                   let id = alertData["id"]?.value as? String,
                   let watchId = alertData["watchId"]?.value as? String,
                   let message = alertData["message"]?.value as? String {
                    let timestamp = alertData["timestamp"]?.value as? String ?? ""
                    let rawData = alertData["data"]?.value as? [String: Any] ?? [:]
                    let dataDict = rawData.compactMapValues { "\($0)" } as [String: String]
                    let alert = MonitoringAlert(
                        id: id,
                        watchlistItemId: watchId,
                        message: message,
                        data: dataDict,
                        timestamp: timestamp
                    )
                    alerts.insert(alert, at: 0)
                }
            default:
                break
            }

        default:
            break
        }
    }

    // MARK: - Mock data

    private func loadMockData() {
        tasks = [.mock, .mockSearching, .mockAwaitingApproval, .mockStopped]
        watchItems = [.mockPriceWatch, .mockNewListing, .mockLineMovement]
        alerts = [.mockPriceDrop, .mockNewApt, .mockLineAlert]
        pendingApprovals = [.mock]
    }
}
