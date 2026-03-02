import Foundation
import Combine

// MARK: - DeepLinkDestination

/// Represents a navigation target resolved from a `clawbot://` URL.
enum DeepLinkDestination: Equatable {
    case task(id: String)
    case approval(id: String)
    case card(id: String)
    case newTask(sharedItemId: String?)

    var description: String {
        switch self {
        case .task(let id):       return "task/\(id)"
        case .approval(let id):   return "approval/\(id)"
        case .card(let id):       return "card/\(id)"
        case .newTask(let itemId): return "task/new\(itemId.map { "?item=\($0)" } ?? "")"
        }
    }
}

// MARK: - DeepLinkHandler

/// Parses `clawbot://` URLs and bridges them into the app's notification-based
/// navigation system. Singleton — attach via `.onOpenURL` in the root view.
///
/// URL format:
///   clawbot://task/{id}
///   clawbot://approval/{id}
///   clawbot://card/{id}
///   clawbot://task/new[?item={sharedItemId}]
@MainActor
class DeepLinkHandler: ObservableObject {

    static let shared = DeepLinkHandler()

    @Published var pendingDestination: DeepLinkDestination?

    private init() {}

    // MARK: - Parse

    /// Parse a URL into a DeepLinkDestination without side effects.
    func parse(url: URL) -> DeepLinkDestination? {
        guard url.scheme == "clawbot" else { return nil }

        let host = url.host()        // e.g. "task", "approval", "card"
        let pathSegments = url.pathComponents.filter { $0 != "/" }

        switch host {
        case "task":
            let firstSegment = pathSegments.first
            if firstSegment == "new" || firstSegment == nil {
                // clawbot://task/new?item=xxx  or  clawbot://task
                let itemId = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                    .queryItems?.first(where: { $0.name == "item" })?.value
                return .newTask(sharedItemId: itemId)
            }
            return .task(id: firstSegment!)

        case "approval":
            guard let id = pathSegments.first else { return nil }
            return .approval(id: id)

        case "card":
            guard let id = pathSegments.first else { return nil }
            return .card(id: id)

        case "new":
            // clawbot://new?item=xxx  (alternative short form)
            let itemId = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "item" })?.value
            return .newTask(sharedItemId: itemId)

        default:
            return nil
        }
    }

    // MARK: - Handle

    /// Parse a URL, store the destination, and post legacy notifications
    /// so existing screens (TaskDetailView, ApprovalsViewModel) can react.
    func handle(url: URL) {
        guard let destination = parse(url: url) else { return }
        pendingDestination = destination

        switch destination {
        case .task(let id):
            NotificationCenter.default.post(
                name: .deepLinkToTask,
                object: nil,
                userInfo: ["taskId": id, "action": "open"]
            )
        case .approval(let id):
            NotificationCenter.default.post(
                name: .deepLinkToApproval,
                object: nil,
                userInfo: ["approvalId": id, "action": "open"]
            )
        case .card, .newTask:
            // No legacy notification — handled via pendingDestination observation
            break
        }
    }

    /// Clear after navigation completes.
    func clearPending() {
        pendingDestination = nil
    }

    // MARK: - Share Extension Pickup

    /// Read any pending shared items from the App Group container and clear them.
    func pickupSharedItems() -> [SharedItem] {
        guard let defaults = UserDefaults(suiteName: SharedKeys.appGroupSuite) else {
            return []
        }
        guard let data = defaults.data(forKey: SharedKeys.pendingItemsKey) else {
            return []
        }

        let items = (try? JSONDecoder().decode([SharedItem].self, from: data)) ?? []

        // Clear after reading
        defaults.removeObject(forKey: SharedKeys.pendingItemsKey)
        return items
    }
}

// MARK: - SharedItem

/// Item received from the share extension via App Group UserDefaults.
struct SharedItem: Codable, Identifiable, Equatable {
    let id: String
    let type: SharedItemType
    let content: String
    let title: String?
    let sourceApp: String?
    let timestamp: String  // ISO 8601

    enum SharedItemType: String, Codable, Equatable {
        case url
        case text
        case image
    }

    init(
        id: String = UUID().uuidString,
        type: SharedItemType,
        content: String,
        title: String? = nil,
        sourceApp: String? = nil,
        timestamp: String = ISO8601DateFormatter().string(from: Date())
    ) {
        self.id = id
        self.type = type
        self.content = content
        self.title = title
        self.sourceApp = sourceApp
        self.timestamp = timestamp
    }
}

// MARK: - SharedKeys

/// Constants for App Group communication with the share extension.
enum SharedKeys {
    static let appGroupSuite = "group.com.clawbot.shared"
    static let pendingItemsKey = "pendingSharedItems"
}

// MARK: - URL Builder

extension DeepLinkHandler {
    /// Build a `clawbot://` URL for a given destination.
    static func url(for destination: DeepLinkDestination) -> URL? {
        switch destination {
        case .task(let id):
            return URL(string: "clawbot://task/\(id)")
        case .approval(let id):
            return URL(string: "clawbot://approval/\(id)")
        case .card(let id):
            return URL(string: "clawbot://card/\(id)")
        case .newTask(let itemId):
            if let itemId {
                return URL(string: "clawbot://task/new?item=\(itemId)")
            }
            return URL(string: "clawbot://task/new")
        }
    }
}
