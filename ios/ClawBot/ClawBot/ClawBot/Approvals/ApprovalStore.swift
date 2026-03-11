import Foundation

// MARK: - ApprovalStore

/// Actor-based approval persistence — single JSON file in Documents/ClawBotApprovals/.
actor ApprovalStore {

    private let directory: URL

    /// Approvals older than this are considered stale on load.
    private let staleThreshold: TimeInterval

    // MARK: - Init

    init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.directory = docs.appendingPathComponent("ClawBotApprovals", isDirectory: true)
        self.staleThreshold = 24 * 60 * 60 // 24 hours
    }

    /// Testable init — inject any directory and optional stale threshold.
    init(directory: URL, staleThreshold: TimeInterval = 24 * 60 * 60) {
        self.directory = directory
        self.staleThreshold = staleThreshold
    }

    // MARK: - Public API

    /// Save pending and resolved approvals. Writes atomically.
    func save(pending: [ApprovalRequest], history: [ResolvedApproval]) throws {
        try ensureDirectory()
        let container = ApprovalStoreData(pending: pending, history: history)
        let data = try encoder.encode(container)
        try data.write(to: fileURL, options: [.atomic])
    }

    /// Load approvals, expiring stale pending requests (older than staleThreshold).
    /// History is never expired. Returns empty collections if the file doesn't exist.
    func load() throws -> (pending: [ApprovalRequest], history: [ResolvedApproval]) {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return (pending: [], history: [])
        }
        let data = try Data(contentsOf: fileURL)
        let decoded = try decoder.decode(ApprovalStoreData.self, from: data)

        let now = Date()
        let formatter = ISO8601DateFormatter()
        let freshPending = decoded.pending.filter { request in
            guard let createdDate = formatter.date(from: request.createdAt) else {
                return false // Can't parse date -> treat as stale
            }
            return now.timeIntervalSince(createdDate) < staleThreshold
        }

        return (pending: freshPending, history: decoded.history)
    }

    /// Remove all persisted approval data.
    func clearAll() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    // MARK: - Private

    private var fileURL: URL {
        directory.appendingPathComponent("approvals.json")
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

private struct ApprovalStoreData: Codable {
    let pending: [ApprovalRequest]
    let history: [ResolvedApproval]
}
