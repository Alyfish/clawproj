import Foundation

// MARK: - DocCard
// Maps to shared/types/cards.ts → DocCard

struct DocCard: Identifiable, Codable, Equatable {
    let id: String
    /// e.g. "google_doc", "google_sheet", "google_form", "google_slides"
    let docType: String
    let title: String
    let previewText: String
    let url: String
    let mimeType: String
    /// ISO 8601 — last time the document was modified
    let lastModified: String?

    /// SF Symbol name for the document type.
    var iconName: String {
        switch docType {
        case "google_doc": return "doc.text"
        case "google_sheet": return "tablecells"
        case "google_form": return "list.clipboard"
        case "google_slides": return "rectangle.on.rectangle"
        default: return "doc"
        }
    }

    /// Color string for the document type icon.
    var iconColor: String {
        switch docType {
        case "google_doc": return "blue"
        case "google_sheet": return "green"
        case "google_form": return "purple"
        case "google_slides": return "orange"
        default: return "gray"
        }
    }
}

// MARK: - Mock Data

extension DocCard {
    static let mockDocument = DocCard(
        id: "doc-1",
        docType: "google_doc",
        title: "Q1 Marketing Strategy",
        previewText: "Overview of the marketing initiatives planned for Q1 2026, including budget allocation and KPIs...",
        url: "https://docs.google.com/document/d/abc123",
        mimeType: "application/vnd.google-apps.document",
        lastModified: "2026-02-27T14:30:00Z"
    )

    static let mockSpreadsheet = DocCard(
        id: "doc-2",
        docType: "google_sheet",
        title: "Expense Tracker 2026",
        previewText: "Monthly expense tracking with categories, totals, and budget comparisons...",
        url: "https://docs.google.com/spreadsheets/d/xyz789",
        mimeType: "application/vnd.google-apps.spreadsheet",
        lastModified: nil
    )
}
