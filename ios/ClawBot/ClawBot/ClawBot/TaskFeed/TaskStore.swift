import Foundation

// MARK: - TaskStore

/// Actor-based task persistence — single JSON file in Documents/ClawBotTasks/.
actor TaskStore {

    private let directory: URL

    // MARK: - Init

    init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.directory = docs.appendingPathComponent("ClawBotTasks", isDirectory: true)
    }

    /// Testable init — inject any directory (e.g. a temp dir).
    init(directory: URL) {
        self.directory = directory
    }

    // MARK: - Public API

    /// Save tasks and pending approvals. Writes atomically.
    func save(tasks: [AgentTask], pendingApprovals: [PendingApproval]) throws {
        try ensureDirectory()
        let container = TaskStoreData(tasks: tasks, pendingApprovals: pendingApprovals)
        let data = try encoder.encode(container)
        try data.write(to: fileURL, options: [.atomic])
    }

    /// Load tasks and pending approvals. Returns empty collections if the file doesn't exist.
    func load() throws -> (tasks: [AgentTask], pendingApprovals: [PendingApproval]) {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return (tasks: [], pendingApprovals: [])
        }
        let data = try Data(contentsOf: fileURL)
        let decoded = try decoder.decode(TaskStoreData.self, from: data)
        return (tasks: decoded.tasks, pendingApprovals: decoded.pendingApprovals)
    }

    /// Remove all persisted task data.
    func clearAll() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    // MARK: - Private

    private var fileURL: URL {
        directory.appendingPathComponent("tasks.json")
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

private struct TaskStoreData: Codable {
    let tasks: [AgentTask]
    let pendingApprovals: [PendingApproval]
}
