import Foundation

// MARK: - MessageStore

/// Actor-based message persistence — one JSON file per session in Documents/ClawBotMessages/.
actor MessageStore {

    private let directory: URL

    // MARK: - Init

    init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.directory = docs.appendingPathComponent("ClawBotMessages", isDirectory: true)
    }

    /// Testable init — inject any directory (e.g. a temp dir).
    init(directory: URL) {
        self.directory = directory
    }

    // MARK: - Public API

    /// Save messages for a session. Filters out streaming messages and writes atomically.
    func save(_ messages: [ChatMessage], sessionId: String) throws {
        try ensureDirectory()

        let filtered = messages.filter { !$0.isStreaming }
        let data = try encoder.encode(filtered)
        try data.write(to: fileURL(for: sessionId), options: [.atomic])
    }

    /// Load messages for a session. Returns `[]` if the file doesn't exist.
    func load(sessionId: String) throws -> [ChatMessage] {
        let url = fileURL(for: sessionId)
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }

        let data = try Data(contentsOf: url)
        return try decoder.decode([ChatMessage].self, from: data)
    }

    /// Delete a single session's messages.
    func delete(sessionId: String) throws {
        let url = fileURL(for: sessionId)
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    /// List all persisted session IDs (derived from filenames).
    func listSessions() throws -> [String] {
        guard FileManager.default.fileExists(atPath: directory.path) else { return [] }

        return try FileManager.default
            .contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
            .map { $0.deletingPathExtension().lastPathComponent }
    }

    /// Total bytes used by all session files.
    func totalSize() throws -> Int {
        guard FileManager.default.fileExists(atPath: directory.path) else { return 0 }

        let files = try FileManager.default
            .contentsOfDirectory(at: directory, includingPropertiesForKeys: [.fileSizeKey])

        return try files.reduce(0) { total, url in
            let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            return total + size
        }
    }

    /// Remove all session files.
    func clearAll() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    // MARK: - Private

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

    /// Sanitize session ID for filename safety — replace `/` and `\` with `_`.
    private func sanitized(_ sessionId: String) -> String {
        sessionId
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
    }

    private func fileURL(for sessionId: String) -> URL {
        directory.appendingPathComponent("\(sanitized(sessionId)).json")
    }

    private func ensureDirectory() throws {
        if !FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
    }
}
