/**
 * AttentionCard - Alert/insight cards for the dashboard
 * 
 * Shows attention-requiring items with:
 * - Severity-coded left border
 * - Inline sparkline for trends
 * - Click to drill into cohort
 */
import { ChevronRight, AlertTriangle, AlertCircle, Info, TrendingUp, Users, DollarSign, X } from 'lucide-react';
import { Sparkline } from './KPIOrb';

interface AttentionCardProps {
  id: number;
  title: string;
  description: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  affectedCount: number;
  trendValue?: number;
  monetaryImpact?: number;
  sparklineData?: number[];
  onClick?: () => void;
  onDismiss?: () => void;
}

export function AttentionCard({
  title,
  description,
  severity,
  affectedCount,
  trendValue,
  monetaryImpact,
  sparklineData,
  onClick,
  onDismiss,
}: AttentionCardProps) {
  const getSeverityConfig = () => {
    // Using neutral backgrounds for all cards as requested
    // Only the left border and icon retain severity color for subtle indication
    switch (severity) {
      case 'critical':
        return {
          border: 'border-l-status-error',
          bg: 'bg-card',
          icon: <AlertCircle className="w-5 h-5 text-status-error" />,
          badge: 'bg-muted text-muted-foreground',
          glow: 'hover:shadow-md',
        };
      case 'high':
        return {
          border: 'border-l-status-warning',
          bg: 'bg-card',
          icon: <AlertTriangle className="w-5 h-5 text-status-warning" />,
          badge: 'bg-muted text-muted-foreground',
          glow: 'hover:shadow-md',
        };
      case 'medium':
        return {
          border: 'border-l-status-info',
          bg: 'bg-card',
          icon: <Info className="w-5 h-5 text-status-info" />,
          badge: 'bg-muted text-muted-foreground',
          glow: 'hover:shadow-md',
        };
      default:
        return {
          border: 'border-l-muted-foreground',
          bg: 'bg-card',
          icon: <Info className="w-5 h-5 text-muted-foreground" />,
          badge: 'bg-muted text-muted-foreground',
          glow: 'hover:shadow-md',
        };
    }
  };

  const config = getSeverityConfig();

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatTrend = (value: number) => {
    const sign = value > 0 ? '+' : '';
    return `${sign}${value}%`;
  };

  return (
    <div
      className={`
        group relative rounded-xl border-l-4 ${config.border}
        ${config.bg} backdrop-blur-sm
        border border-border hover:border-muted-foreground/30
        transition-all duration-300 ${config.glow}
        ${onClick ? 'cursor-pointer' : ''}
      `}
      onClick={onClick}
    >
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-3">
            {config.icon}
            <h3 className="font-medium text-foreground">{title}</h3>
          </div>
          
          <div className="flex items-center gap-2">
            {onDismiss && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDismiss();
                }}
                className="p-1 rounded-md opacity-0 group-hover:opacity-100
                         hover:bg-muted transition-all"
              >
                <X className="w-4 h-4 text-muted-foreground" />
              </button>
            )}
            
            {onClick && (
              <div className="flex items-center gap-1 text-sm text-muted-foreground 
                            group-hover:text-foreground/70 transition-colors">
                <span>View</span>
                <ChevronRight className="w-4 h-4" />
              </div>
            )}
          </div>
        </div>

        {/* Description */}
        <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
          {description}
        </p>

        {/* Stats row */}
        <div className="flex items-center gap-4 text-sm">
          {/* Affected count */}
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Users className="w-4 h-4" />
            <span className="font-mono-data">{affectedCount}</span>
            <span className="text-muted-foreground/70">affected</span>
          </div>

          {/* Trend */}
          {trendValue != null && (
            <div className={`flex items-center gap-1 ${
              trendValue > 0 ? 'text-status-error' : 'text-status-success'
            }`}>
              <TrendingUp className="w-4 h-4" />
              <span className="font-mono-data">{formatTrend(trendValue)}</span>
              <span className="text-muted-foreground/70">vs last week</span>
            </div>
          )}

          {/* Monetary impact */}
          {monetaryImpact !== undefined && monetaryImpact > 0 && (
            <div className="flex items-center gap-1 text-status-warning">
              <DollarSign className="w-4 h-4" />
              <span className="font-mono-data">{formatCurrency(monetaryImpact)}</span>
              <span className="text-muted-foreground/70">at risk</span>
            </div>
          )}
        </div>

        {/* Sparkline */}
        {sparklineData && sparklineData.length > 0 && (
          <div className="mt-3 h-8 opacity-60 group-hover:opacity-100 transition-opacity">
            <Sparkline 
              data={sparklineData} 
              height={32}
              color={severity === 'critical' ? '#ef4444' : 
                     severity === 'high' ? '#f59e0b' : 
                     '#3b82f6'}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default AttentionCard;
