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
        loadMockData()

        webSocket.streamEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleEvent(event)
            }
            .store(in: &cancellables)
    }

    // MARK: - Public actions

    func refresh() async {
        // MVP: reload mock data. Replace with real API fetch later.
        loadMockData()
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
        let message = WSMessage.request(
            method: "watchlist.toggle",
            id: UUID().uuidString,
            payload: [
                "watchlistItemId": AnyCodable(item.id),
                "active": AnyCodable(active),
            ]
        )
        webSocket.send(message)
        // Optimistic update
        if let index = watchItems.firstIndex(where: { $0.id == item.id }) {
            watchItems[index].active = active
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
            guard let index = tasks.firstIndex(where: { $0.id == taskId }) else { return }
            if let newStatus = TaskStatus(rawValue: status) {
                tasks[index].status = newStatus
            }
            if let step {
                // Replace existing step or append
                if let stepIndex = tasks[index].steps.firstIndex(where: { $0.id == step.id }) {
                    tasks[index].steps[stepIndex] = step
                } else {
                    tasks[index].steps.append(step)
                }
            }
            tasks[index].updatedAt = ISO8601DateFormatter().string(from: Date())

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
