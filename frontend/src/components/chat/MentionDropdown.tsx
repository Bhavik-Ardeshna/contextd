import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { getAppIconUrl } from '@/lib/utils/icons';
import { useTheme } from '@/lib/theme-provider';

export interface Connector {
  id: string;
  name: string;
}

export const CONNECTORS: Connector[] = [
  { id: 'search', name: 'Search' },
  { id: 'clickhouse', name: 'ClickHouse' },
  { id: 'postgresql', name: 'PostgreSQL' },
  { id: 'asana', name: 'Asana' },
  { id: 'slack', name: 'Slack' },
  { id: 'notion', name: 'Notion' },
  { id: 'github', name: 'GitHub' },
  { id: 'google_drive', name: 'Google Drive' },
  { id: 'jira', name: 'Jira' },
  { id: 'confluence', name: 'Confluence' },
  { id: 'hubspot', name: 'HubSpot' },
  { id: 'salesforce', name: 'Salesforce' },
  { id: 'zendesk', name: 'Zendesk' },
  { id: 'intercom', name: 'Intercom' },
  { id: 'linear', name: 'Linear' },
  { id: 'clickup', name: 'ClickUp' },
  { id: 'trello', name: 'Trello' },
  { id: 'monday', name: 'Monday' },
  { id: 'airtable', name: 'Airtable' },
  { id: 'dropbox', name: 'Dropbox' },
  { id: 'box', name: 'Box' },
  { id: 'outlook_mail', name: 'Outlook' },
  { id: 'teams', name: 'Teams' },
  { id: 'sharepoint', name: 'SharePoint' },
  { id: 'onedrive', name: 'OneDrive' },
  { id: 'todoist', name: 'Todoist' },
  { id: 'calendly', name: 'Calendly' },
  { id: 'attio', name: 'Attio' },
  { id: 'pipedrive', name: 'Pipedrive' },
  { id: 'stripe', name: 'Stripe' },
  { id: 'shopify', name: 'Shopify' },
  { id: 'gitlab', name: 'GitLab' },
  { id: 'bitbucket', name: 'Bitbucket' },
  { id: 'gmail', name: 'Gmail' },
].sort((a, b) => a.name.localeCompare(b.name));

interface MentionDropdownProps {
  items: Connector[];
  selectedIndex: number;
  onSelect: (item: Connector) => void;
  /** When provided, renders via a portal anchored above this element (bypasses CSS stacking contexts) */
  anchorEl?: HTMLElement | null;
  className?: string;
}

export function MentionDropdown({ items, selectedIndex, onSelect, anchorEl, className = '' }: MentionDropdownProps) {
  const { resolvedTheme } = useTheme();
  const listRef = useRef<HTMLDivElement>(null);
  const [portalStyle, setPortalStyle] = useState<React.CSSProperties>({});

  // Compute fixed position from anchor element's bounding rect
  useEffect(() => {
    if (!anchorEl) return;
    const rect = anchorEl.getBoundingClientRect();
    setPortalStyle({
      position: 'fixed',
      bottom: window.innerHeight - rect.top + 8,
      left: rect.left,
      zIndex: 9999,
    });
  }, [anchorEl, items]);

  // Auto-scroll to selected item
  useEffect(() => {
    if (listRef.current && selectedIndex >= 0) {
      const selectedEl = listRef.current.children[selectedIndex] as HTMLElement;
      if (selectedEl) {
        selectedEl.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  if (items.length === 0) return null;

  const listContent = (
    <div
      ref={listRef}
      style={anchorEl ? portalStyle : undefined}
      className={`w-64 max-h-64 overflow-y-auto rounded-xl border border-border bg-card shadow-xl p-1 scrollbar-thin ${anchorEl ? '' : `absolute z-50 ${className}`}`}
    >
      {items.map((item, idx) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onSelect(item)}
          className={`flex items-center gap-2 w-full px-3 py-2 text-sm rounded-lg transition-colors cursor-pointer text-left
            ${idx === selectedIndex ? 'bg-muted/80 text-foreground' : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'}
          `}
        >
          <div className="flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center bg-background border border-border">
            <img
              src={getAppIconUrl(item.id, resolvedTheme)}
              alt={item.name}
              className="w-4 h-4 object-contain"
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
            />
          </div>
          <span className="font-medium">{item.name}</span>
        </button>
      ))}
    </div>
  );

  if (anchorEl) {
    return createPortal(listContent, document.body);
  }

  return listContent;
}

// Hook to manage mention logic
export function useMention(inputValue: string) {
  // Matches '@word' at the end of the input (or just before cursor if we supported cursor pos, but here we assume end)
  const match = inputValue.match(/(?:^|\s)(@\w*)$/);
  const isActive = match !== null;
  const mentionQuery = isActive ? match[1].slice(1).toLowerCase() : '';

  const filteredItems = isActive
    ? CONNECTORS.filter(c =>
        c.name.toLowerCase().includes(mentionQuery) ||
        c.id.toLowerCase().includes(mentionQuery)
      )
    : [];

  const handleMentionSelect = (item: Connector, currentInput: string) => {
    if (!match) return currentInput;
    // Replace the matched "@query" with "@ConnectorName "
    const mentionText = `@${item.name} `;
    return currentInput.slice(0, match.index! + (match[0].startsWith(' ') ? 1 : 0)) + mentionText;
  };

  return {
    isActive,
    mentionQuery,
    filteredItems,
    handleMentionSelect
  };
}
