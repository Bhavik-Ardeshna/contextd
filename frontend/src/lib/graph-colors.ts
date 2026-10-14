/**
 * Graph Color System for Knowledge Graph Visualization
 * 
 * Provides a standardized color palette and utilities for node/edge coloring
 * that works with ContextD's theming system and supports dynamic assignment
 * for unlimited connector types.
 */

// =============================================================================
// COLOR PALETTES
// =============================================================================

/**
 * Primary color palette for graph nodes
 * These colors are from the purple/violet spectrum matching the design system
 * Used for hash-based assignment to unknown node types
 */
export const GRAPH_COLOR_PALETTE = [
  '#a855f7', // Primary purple - hsl(265, 89%, 50%)
  '#c084fc', // Purple-400
  '#a78bfa', // Violet-400
  '#8b5cf6', // Violet-500
  '#9ca3af', // Gray-400
  '#6b7280', // Gray-500
  '#e879f9', // Fuchsia-400
  '#f472b6', // Pink-400
  '#818cf8', // Indigo-400
  '#60a5fa', // Blue-400
  '#34d399', // Emerald-400
  '#fbbf24', // Amber-400
  '#fb923c', // Orange-400
  '#f87171', // Red-400
  '#a3e635', // Lime-400
] as const;

/**
 * Edge color palette for relationship types
 * Provides visual distinction between different relationship types
 */
export const EDGE_COLOR_PALETTE = [
  '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
  '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
] as const;

/**
 * Known node type color mappings
 * These override the hash-based assignment for specific important types
 * Organized by connector/entity category
 */
export const KNOWN_NODE_COLORS: Record<string, string> = {
  // Notion entities
  'NotionPageEntity': '#E07A5F',
  'NotionDatabaseEntity': '#F2CC8F',
  'NotionBlockEntity': '#c084fc',
  
  // Asana entities
  'AsanaTaskEntity': '#81B29A',
  'AsanaProjectEntity': '#3D9970',
  'AsanaSectionEntity': '#2ECC40',
  'AsanaUserEntity': '#3D5A80',
  
  // ClickUp entities
  'ClickUpTaskEntity': '#FF851B',
  'ClickUpSubtaskEntity': '#FF9133',
  'ClickUpListEntity': '#FF4136',
  'ClickUpSpaceEntity': '#B10DC9',
  'ClickUpWorkspaceEntity': '#85144b',
  'ClickUpFolderEntity': '#a855f7',
  'ClickUpCommentEntity': '#FFDC00',
  'ClickUpFileNode': '#9ca3af',
  'ClickUpCommentNode': '#FFDC00',
  'ClickUpTaskNode': '#FF851B',
  'ClickUpSubtaskNode': '#FF9133',
  'ClickUpListNode': '#FF4136',
  'ClickUpSpaceNode': '#B10DC9',
  'ClickUpWorkspaceNode': '#85144b',
  'ClickUpFolderNode': '#a855f7',
  
  // Generic/common node types
  'PersonNode': '#3D5A80',
  'ProjectNode': '#98C1D9',
  'StatusNode': '#7FDBFF',
  'PriorityNode': '#FFDC00',
  'TagNode': '#01FF70',
  'FileNode': '#9ca3af',
  'DocumentNode': '#c084fc',
  'CommentNode': '#a78bfa',
  
  // Slack entities
  'SlackMessageEntity': '#4A154B',
  'SlackChannelEntity': '#36C5F0',
  'SlackUserEntity': '#2EB67D',
  
  // Google entities
  'GoogleDriveFileEntity': '#4285F4',
  'GoogleDocEntity': '#4285F4',
  'GoogleSheetEntity': '#0F9D58',
  'GoogleSlideEntity': '#F4B400',
  
  // GitHub entities
  'GitHubRepoEntity': '#24292e',
  'GitHubIssueEntity': '#238636',
  'GitHubPREntity': '#8957e5',
  'GitHubUserEntity': '#f78166',
  
  // Jira entities
  'JiraIssueEntity': '#0052CC',
  'JiraProjectEntity': '#00875A',
  'JiraSprintEntity': '#FF5630',

  // Salesforce entities
  'SalesforceAccountEntity': '#00A1E0',
  'SalesforceContactEntity': '#1589EE',
  'SalesforceOpportunityEntity': '#1798C1',

  // Linear entities
  'LinearIssueEntity': '#5E6AD2',
  'LinearProjectEntity': '#5E6AD2',
  'LinearTeamEntity': '#5E6AD2',
  
  // Default fallback
  'default': '#6b7280',
};

/**
 * Node sizes based on entity type importance
 * Larger sizes for more important/central nodes
 */
export const NODE_SIZES: Record<string, number> = {
  // High importance - workspace/project level
  'NotionDatabaseEntity': 18,
  'AsanaProjectEntity': 18,
  'ClickUpWorkspaceEntity': 20,
  'ClickUpSpaceEntity': 18,
  'ProjectNode': 18,
  'JiraProjectEntity': 18,
  'LinearProjectEntity': 18,
  'GitHubRepoEntity': 18,
  'SalesforceAccountEntity': 18,

  // Medium importance - task/page level
  'NotionPageEntity': 15,
  'AsanaTaskEntity': 15,
  'ClickUpTaskEntity': 15,
  'ClickUpListEntity': 15,
  'JiraIssueEntity': 15,
  'LinearIssueEntity': 15,
  'GitHubIssueEntity': 15,
  'GitHubPREntity': 15,
  'PersonNode': 16,
  'SalesforceContactEntity': 15,
  'SalesforceOpportunityEntity': 15,

  // Lower importance - supporting entities
  'AsanaSectionEntity': 12,
  'ClickUpFolderEntity': 12,
  'NotionBlockEntity': 10,
  'CommentNode': 10,
  'TagNode': 10,
  'StatusNode': 12,
  'PriorityNode': 12,
  
  // Default size
  'default': 15,
};

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Simple string hash function for deterministic color assignment
 * Uses djb2 algorithm for good distribution
 */
function hashString(str: string): number {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) + str.charCodeAt(i);
  }
  return Math.abs(hash);
}

/**
 * Get color for a node type
 * First checks known mappings, then falls back to hash-based assignment
 */
export function getNodeColor(nodeType: string): string {
  // Check for known mappings first
  if (KNOWN_NODE_COLORS[nodeType]) {
    return KNOWN_NODE_COLORS[nodeType];
  }
  
  // Fall back to hash-based assignment for unknown types
  const hash = hashString(nodeType);
  return GRAPH_COLOR_PALETTE[hash % GRAPH_COLOR_PALETTE.length];
}

/**
 * Get color for an edge/relationship type
 */
export function getEdgeColor(relationshipType: string): string {
  const hash = hashString(relationshipType);
  return EDGE_COLOR_PALETTE[hash % EDGE_COLOR_PALETTE.length];
}

/**
 * Get size for a node type
 */
export function getNodeSize(nodeType: string): number {
  return NODE_SIZES[nodeType] || NODE_SIZES.default;
}

/**
 * Format edge type for display (convert snake_case to Title Case)
 */
export function formatEdgeType(type: string): string {
  return type
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

// =============================================================================
// THEME-AWARE COLORS
// =============================================================================

/**
 * Theme-aware highlight colors for graph interactions
 * These should match the CSS variables defined in index.css
 */
export interface HighlightColors {
  primary: string;
  secondary: string;
  dimmedNode: string;
  dimmedEdge: string;
  labelHighlighted: string;
  labelNeighbor: string;
  labelDefault: string;
}

/**
 * Get theme-aware highlight colors
 * Returns colors that work well with the current theme
 */
export function getHighlightColors(isDark: boolean): HighlightColors {
  if (isDark) {
    return {
      primary: '#a855f7',           // Primary purple
      secondary: '#c084fc',         // Purple-400
      dimmedNode: '#404040',        // Gray for dimmed nodes
      dimmedEdge: 'rgba(75, 85, 99, 0.15)', // Nearly invisible
      labelHighlighted: '#a855f7',  // Primary purple for highlighted labels
      labelNeighbor: '#c084fc',     // Purple-400 for neighbor labels
      labelDefault: '#9ca3af',      // Gray-400 for default labels
    };
  }
  
  return {
    primary: '#a855f7',           // Primary purple
    secondary: '#a78bfa',         // Violet-400
    dimmedNode: '#d4d4d4',        // Light gray for dimmed nodes
    dimmedEdge: 'rgba(229, 231, 235, 0.15)', // Nearly invisible
    labelHighlighted: '#a855f7',  // Primary purple for highlighted labels
    labelNeighbor: '#a78bfa',     // Violet-400 for neighbor labels  
    labelDefault: '#6b7280',      // Gray-500 for default labels
  };
}

/**
 * Get graph background and text colors based on theme
 */
export function getThemeColors(isDark: boolean) {
  return {
    background: isDark ? '#060606' : '#f9fafb',
    labelColor: isDark ? '#fafafa' : '#374151',
    edgeLabelColor: isDark ? '#d4d4d4' : '#6b7280',
    edgeColor: isDark ? '#4b5563' : '#9ca3af',
  };
}

// =============================================================================
// LEGEND HELPERS
// =============================================================================

/**
 * Get a list of node types and their colors for the legend
 * Filters to show only types that exist in the current graph
 */
export function getLegendItems(nodeTypes: string[]): Array<{ label: string; color: string }> {
  const uniqueTypes = [...new Set(nodeTypes)];
  return uniqueTypes.map(type => ({
    label: type.replace(/Entity$/, '').replace(/Node$/, ''),
    color: getNodeColor(type),
  }));
}

/**
 * Default legend items to show when no nodes are selected
 */
export const DEFAULT_LEGEND_ITEMS = [
  { label: 'Notion Page', color: KNOWN_NODE_COLORS['NotionPageEntity'] },
  { label: 'Asana Task', color: KNOWN_NODE_COLORS['AsanaTaskEntity'] },
  { label: 'ClickUp Task', color: KNOWN_NODE_COLORS['ClickUpTaskEntity'] },
  { label: 'Person', color: KNOWN_NODE_COLORS['PersonNode'] },
  { label: 'Salesforce Account', color: KNOWN_NODE_COLORS['SalesforceAccountEntity'] },
  { label: 'Salesforce Opportunity', color: KNOWN_NODE_COLORS['SalesforceOpportunityEntity'] },
];
