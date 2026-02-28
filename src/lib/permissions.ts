export type RiskLevel = 'HIGH' | 'MED' | 'LOW'

export interface Scope {
  id: string
  label: string
  description: string
  risk: RiskLevel
}

export const SCOPES: Scope[] = [
  { id: 'gmail.read', label: 'Read Gmail', description: 'Access your email inbox and read messages', risk: 'HIGH' },
  { id: 'web.search', label: 'Web Search', description: 'Search the web on your behalf', risk: 'MED' },
  { id: 'reminders.write', label: 'Write Reminders', description: 'Create and manage reminders', risk: 'LOW' },
  { id: 'contacts.read', label: 'Read Contacts', description: 'Access your contact list', risk: 'MED' },
  { id: 'calendar.read', label: 'Read Calendar', description: 'View your calendar events', risk: 'MED' },
]

export function getScope(id: string): Scope | undefined {
  return SCOPES.find(s => s.id === id)
}
