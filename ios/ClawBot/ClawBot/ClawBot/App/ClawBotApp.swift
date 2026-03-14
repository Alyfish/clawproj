import SwiftUI
import UserNotifications

@main
struct ClawBotApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var deepLinkHandler = DeepLinkHandler.shared
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false

    var body: some Scene {
        WindowGroup {
            if hasCompletedOnboarding {
                mainContent
            } else {
                OnboardingFlow(onComplete: { hasCompletedOnboarding = true })
                    .onContinueUserActivity("com.apple.authentication-services.credential-exchange") { activity in
                        handleCXPImport(activity: activity)
                    }
            }
        }
    }

    @ViewBuilder
    private var mainContent: some View {
        ContentView()
            .environmentObject(deepLinkHandler)
            .onOpenURL { url in
                deepLinkHandler.handle(url: url)
            }
            .onAppear {
                NotificationManager.shared.setup()
                pickupSharedItems()
            }
            .onContinueUserActivity("com.apple.authentication-services.credential-exchange") { activity in
                handleCXPImport(activity: activity)
            }
            .onReceive(
                NotificationCenter.default.publisher(
                    for: UIApplication.didBecomeActiveNotification
                )
            ) { _ in
                pickupSharedItems()
            }
    }

    private func handleCXPImport(activity: NSUserActivity) {
        if #available(iOS 26, *) {
            Task {
                let handler = CXPImportHandler()
                let count = await handler.handleImport(activity: activity)
                #if DEBUG
                print("[ClawBotApp] CXP imported \(count) credential(s)")
                #endif
            }
        }
    }

    private func pickupSharedItems() {
        let items = deepLinkHandler.pickupSharedItems()
        guard !items.isEmpty else { return }
        #if DEBUG
        print("[ClawBotApp] picked up \(items.count) shared item(s)")
        #endif
        // Post notification so ChatViewModel or TaskFeedViewModel can ingest them
        NotificationCenter.default.post(
            name: .sharedItemsReceived,
            object: nil,
            userInfo: ["items": items]
        )
    }
}

// MARK: - AppDelegate

class AppDelegate: NSObject, UIApplicationDelegate {

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = NotificationManager.shared
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        NotificationManager.shared.didRegisterForRemoteNotifications(withDeviceToken: deviceToken)
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        NotificationManager.shared.didFailToRegisterForRemoteNotifications(withError: error)
    }
}

// MARK: - Notification.Name

extension Notification.Name {
    static let sharedItemsReceived = Notification.Name("sharedItemsReceived")
}
