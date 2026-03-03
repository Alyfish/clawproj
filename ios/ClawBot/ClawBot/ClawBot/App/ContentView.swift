import SwiftUI

struct ContentView: View {
    @StateObject private var webSocket: WebSocketService
    @StateObject private var taskViewModel: TaskFeedViewModel
    @StateObject private var approvalsViewModel: ApprovalsViewModel

    init() {
        let ws = WebSocketService()
        _webSocket = StateObject(wrappedValue: ws)
        _taskViewModel = StateObject(wrappedValue: TaskFeedViewModel(webSocket: ws))
        _approvalsViewModel = StateObject(wrappedValue: ApprovalsViewModel(webSocket: ws))
    }

    var body: some View {
        TabView {
            ChatView(webSocket: webSocket)
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right")
                }

            tasksTab
                .tabItem {
                    Label("Tasks", systemImage: "checklist")
                }

            approvalsTab
                .tabItem {
                    Label("Approvals", systemImage: "checkmark.shield")
                }
                .badge(approvalsViewModel.pendingCount)

            watchlistsTab
                .tabItem {
                    Label("Watchlists", systemImage: "eye")
                }
                .badge(taskViewModel.alertBadgeCount)
        }
    }

    // MARK: - Tasks Tab

    private var tasksTab: some View {
        NavigationStack {
            TaskFeedView(
                tasks: taskViewModel.tasks,
                onRefresh: { await taskViewModel.refresh() },
                onSelectTask: { task in taskViewModel.selectedTask = task }
            )
            .navigationDestination(item: $taskViewModel.selectedTask) { task in
                TaskDetailView(
                    task: task,
                    pendingApprovals: taskViewModel.pendingApprovals,
                    onStopTask: { taskViewModel.stopTask($0) },
                    onApprove: { taskViewModel.approveAction($0) },
                    onDeny: { taskViewModel.denyAction($0) }
                )
            }
        }
    }

    // MARK: - Approvals Tab

    private var approvalsTab: some View {
        NavigationStack {
            ApprovalsListView(
                pending: approvalsViewModel.pending,
                history: approvalsViewModel.history,
                onSelectPending: { request in
                    approvalsViewModel.selectedApproval = request
                }
            )
            .navigationDestination(item: $approvalsViewModel.selectedApproval) { request in
                ApprovalDetailView(
                    request: request,
                    onApprove: { approvalsViewModel.approve($0) },
                    onDeny: { approvalsViewModel.deny($0) }
                )
            }
        }
    }

    // MARK: - Watchlists Tab

    private var watchlistsTab: some View {
        NavigationStack {
            WatchlistView(
                items: taskViewModel.watchItems,
                alerts: taskViewModel.alerts,
                onToggleActive: { item, active in taskViewModel.toggleWatchActive(item, active: active) },
                onSelectItem: { item in taskViewModel.selectedWatchItem = item }
            )
            .navigationDestination(item: $taskViewModel.selectedWatchItem) { item in
                WatchlistDetailView(
                    item: item,
                    alerts: taskViewModel.alerts
                )
            }
        }
    }
}

#Preview {
    ContentView()
}
