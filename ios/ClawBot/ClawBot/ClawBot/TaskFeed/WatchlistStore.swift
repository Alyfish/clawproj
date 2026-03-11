import Foundation

// MARK: - WatchlistStore

/// Actor-based watchlist persistence — single JSON file in Documents/ClawBotWatchlists/.
actor WatchlistStore {

    private let directory: URL

    /// Maximum alerts to persist.
    static let alertCap = 100

    // MARK: - Init

    init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.directory = docs.appendingPathComponent("ClawBotWatchlists", isDirectory: true)
    }

    /// Testable init — inject any directory.
    init(directory: URL) {
        self.directory = directory
    }

    // MARK: - Public API

    /// Save watchlist items and alerts. Caps alerts at 100. Writes atomically.
    func save(items: [WatchlistItem], alerts: [WatchlistAlert]) throws {
        try ensureDirectory()
        let cappedAlerts = Array(alerts.prefix(Self.alertCap))
        let container = WatchlistStoreData(items: items, alerts: cappedAlerts)
        let data = try encoder.encode(container)
        try data.write(to: fileURL, options: [.atomic])
    }

    /// Load watchlist items and alerts. Caps alerts at 100.
    /// Returns empty collections if the file doesn't exist.
    func load() throws -> (items: [WatchlistItem], alerts: [WatchlistAlert]) {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return (items: [], alerts: [])
        }
        let data = try Data(contentsOf: fileURL)
        let decoded = try decoder.decode(WatchlistStoreData.self, from: data)
        let cappedAlerts = Array(decoded.alerts.prefix(Self.alertCap))
        return (items: decoded.items, alerts: cappedAlerts)
    }

    /// Remove all persisted watchlist data.
    func clearAll() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    // MARK: - Private

    private var fileURL: URL {
        directory.appendingPathComponent("watchlists.json")
    }

    private lazy var encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.sortedKeys]
        return e
    }()

    private lazy var decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    private func ensureDirectory() throws {
        if !FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
    }
}

// MARK: - Storage container

private struct WatchlistStoreData: Codable {
    let items: [WatchlistItem]
    let alerts: [WatchlistAlert]
}
