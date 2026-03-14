import SwiftUI

struct ContentView: View {
    @StateObject private var webSocket: WebSocketService
    @StateObject private var taskViewModel: TaskFeedViewModel
    @StateObject private var approvalsViewModel: ApprovalsViewModel
    @StateObject private var credentialHandler: CredentialRequestHandler
    @StateObject private var tokenRefreshHandler: OAuthTokenRefreshHandler

    @State private var selectedTab = 0

    init() {
        let ws = WebSocketService()
        _webSocket = StateObject(wrappedValue: ws)
        _taskViewModel = StateObject(wrappedValue: TaskFeedViewModel(
            webSocket: ws,
            taskStore: TaskStore(),
            watchlistStore: WatchlistStore()
        ))
        _approvalsViewModel = StateObject(wrappedValue: ApprovalsViewModel(
            webSocket: ws,
            approvalStore: ApprovalStore()
        ))
        _credentialHandler = StateObject(wrappedValue: CredentialRequestHandler(webSocket: ws))
        _tokenRefreshHandler = StateObject(wrappedValue: OAuthTokenRefreshHandler(webSocket: ws))
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            ChatView(webSocket: webSocket)
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right")
                }
                .tag(0)

            tasksTab
                .tabItem {
                    Label("Tasks", systemImage: "checklist")
                }
                .tag(1)

            approvalsTab
                .tabItem {
                    Label("Approvals", systemImage: "checkmark.shield")
                }
                .badge(approvalsViewModel.pendingCount)
                .tag(2)

            watchlistsTab
                .tabItem {
                    Label("Watchlists", systemImage: "eye")
                }
                .badge(taskViewModel.alertBadgeCount)
                .tag(3)

            #if DEBUG
            NavigationStack {
                DebugCredentialView()
            }
            .tabItem {
                Label("Debug", systemImage: "hammer")
            }
            .tag(4)
            #endif
        }
        .overlay(alignment: .top) {
            if let alert = taskViewModel.bannerAlert {
                AlertBannerView(
                    alert: alert,
                    onTap: {
                        taskViewModel.markAsRead(alert.id)
                        taskViewModel.dismissBanner()
                        selectedTab = 3
                    },
                    onDismiss: {
                        taskViewModel.dismissBanner()
                    }
                )
                .transition(.move(edge: .top).combined(with: .opacity))
                .padding(.top, 50)
                .zIndex(100)
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: taskViewModel.bannerAlert != nil)
        .task {
            await taskViewModel.loadPersistedData()
            await approvalsViewModel.loadPersistedData()
            credentialHandler.start()
            tokenRefreshHandler.start()
            await GoogleOAuthManager.shared.refreshIfNeeded()
        }
        .onReceive(NotificationCenter.default.publisher(for: .deepLinkToWatchlist)) { notification in
            if let watchId = notification.userInfo?["watchId"] as? String {
                selectedTab = 3
                taskViewModel.markAsRead(watchId)
            }
        }
        .onChange(of: taskViewModel.bannerAlert?.id) { _, newId in
            // Auto-dismiss banner after 5 seconds
            if newId != nil {
                Task {
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                    taskViewModel.dismissBanner()
                }
            }
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
                onSelectItem: { item in taskViewModel.selectedWatchItem = item },
                onMarkAsRead: { alertId in taskViewModel.markAsRead(alertId) },
                onMarkAllAsRead: { taskViewModel.markAllAsRead() },
                onAlertTap: { alert in
                    if let urlString = alert.url, let url = URL(string: urlString) {
                        UIApplication.shared.open(url)
                    }
                }
            )
            .navigationDestination(item: $taskViewModel.selectedWatchItem) { item in
                WatchlistDetailView(
                    item: item,
                    alerts: taskViewModel.alerts,
                    onMarkAsRead: { alertId in taskViewModel.markAsRead(alertId) }
                )
            }
        }
    }
}

// MARK: - Alert Banner View

private struct AlertBannerView: View {
    let alert: WatchlistAlert
    let onTap: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: alert.alertIcon)
                .foregroundColor(alert.alertColor)
                .font(.title2)

            VStack(alignment: .leading, spacing: 2) {
                Text(alert.title)
                    .font(.subheadline.bold())
                    .lineLimit(1)
                Text(alert.message)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }

            Spacer()

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.caption.bold())
                    .foregroundColor(.secondary)
                    .padding(6)
            }
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 4)
        .padding(.horizontal)
        .contentShape(Rectangle())
        .onTapGesture(perform: onTap)
    }
}

#Preview {
    ContentView()
}
