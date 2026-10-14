/**
 * Utility to parse cron expressions and return human-readable descriptions
 */

export interface ParsedCron {
  description: string;
  shortDescription: string;
  descriptionLocal: string;
  shortDescriptionLocal: string;
  nextRun?: Date;
}

/**
 * Parse a cron expression and return a human-readable description
 * @param cronExpression - The cron expression to parse (5 parts: minute hour day month weekday)
 * @returns Parsed cron with descriptions
 */
export function parseCronExpression(cronExpression: string | undefined | null): ParsedCron | null {
  if (!cronExpression) return null;

  const parts = cronExpression.split(' ');
  if (parts.length !== 5) return null;

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  // Handle common patterns
  // Every X hours
  if (minute !== '*' && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    if (minute === '0') {
      return {
        description: 'Every hour',
        shortDescription: 'Hourly',
        descriptionLocal: 'Every hour',
        shortDescriptionLocal: 'Hourly'
      };
    }
    return {
      description: `Every hour at ${minute} minutes`,
      shortDescription: `Hourly :${minute.padStart(2, '0')}`,
      descriptionLocal: `Every hour at ${minute} minutes`,
      shortDescriptionLocal: `Hourly :${minute.padStart(2, '0')}`
    };
  }

  // Every X hours (using */X pattern)
  if (minute === '0' && hour.startsWith('*/') && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const interval = hour.substring(2);
    if (interval === '1') {
      return {
        description: 'Every hour',
        shortDescription: 'Hourly',
        descriptionLocal: 'Every hour',
        shortDescriptionLocal: 'Hourly'
      };
    }
    return {
      description: `Every ${interval} hours`,
      shortDescription: `Every ${interval}h`,
      descriptionLocal: `Every ${interval} hours`,
      shortDescriptionLocal: `Every ${interval}h`
    };
  }

  // Daily at specific time
  if (minute !== '*' && hour !== '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const hourNum = parseInt(hour);
    const minuteNum = parseInt(minute);
    const timeUTC = formatTime(hourNum, minuteNum);
    const timeLocal = formatLocalTime(hourNum, minuteNum);
    return {
      description: `Daily at ${timeUTC.full} UTC`,
      shortDescription: `Daily ${timeUTC.short}`,
      descriptionLocal: `Daily at ${timeLocal.full}`,
      shortDescriptionLocal: `Daily ${timeLocal.short}`
    };
  }

  // Weekly on specific day
  if (minute !== '*' && hour !== '*' && dayOfMonth === '*' && month === '*' && dayOfWeek !== '*') {
    const hourNum = parseInt(hour);
    const minuteNum = parseInt(minute);
    const timeUTC = formatTime(hourNum, minuteNum);
    const timeLocal = formatLocalTime(hourNum, minuteNum);
    const dayName = getDayName(dayOfWeek);
    return {
      description: `Every ${dayName} at ${timeUTC.full} UTC`,
      shortDescription: `${dayName}s ${timeUTC.short}`,
      descriptionLocal: `Every ${dayName} at ${timeLocal.full}`,
      shortDescriptionLocal: `${dayName}s ${timeLocal.short}`
    };
  }

  // Monthly on specific day
  if (minute !== '*' && hour !== '*' && dayOfMonth !== '*' && month === '*' && dayOfWeek === '*') {
    const hourNum = parseInt(hour);
    const minuteNum = parseInt(minute);
    const timeUTC = formatTime(hourNum, minuteNum);
    const timeLocal = formatLocalTime(hourNum, minuteNum);
    const dayStr = dayOfMonth === '1' ? '1st' :
                   dayOfMonth === '2' ? '2nd' :
                   dayOfMonth === '3' ? '3rd' :
                   `${dayOfMonth}th`;
    return {
      description: `Monthly on the ${dayStr} at ${timeUTC.full} UTC`,
      shortDescription: `Monthly ${dayStr}`,
      descriptionLocal: `Monthly on the ${dayStr} at ${timeLocal.full}`,
      shortDescriptionLocal: `Monthly ${dayStr}`
    };
  }

  // Every few minutes
  if (minute.startsWith('*/') && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const interval = minute.substring(2);
    if (interval === '1') {
      return {
        description: 'Every minute',
        shortDescription: 'Every min',
        descriptionLocal: 'Every minute',
        shortDescriptionLocal: 'Every min'
      };
    }
    return {
      description: `Every ${interval} minutes`,
      shortDescription: `Every ${interval}m`,
      descriptionLocal: `Every ${interval} minutes`,
      shortDescriptionLocal: `Every ${interval}m`
    };
  }

  // Specific minute every hour
  if (minute !== '*' && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    const minuteNum = parseInt(minute);
    return {
      description: `Every hour at ${minuteNum} minutes past`,
      shortDescription: `Hourly :${minute.padStart(2, '0')}`,
      descriptionLocal: `Every hour at ${minuteNum} minutes past`,
      shortDescriptionLocal: `Hourly :${minute.padStart(2, '0')}`
    };
  }

  // Default: show the raw cron
  return {
    description: `Custom schedule: ${cronExpression}`,
    shortDescription: 'Custom',
    descriptionLocal: `Custom schedule: ${cronExpression}`,
    shortDescriptionLocal: 'Custom'
  };
}

/**
 * Format time for display
 */
function formatTime(hour: number, minute: number): { full: string; short: string } {
  const period = hour >= 12 ? 'PM' : 'AM';
  const displayHour = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
  const minuteStr = minute.toString().padStart(2, '0');

  return {
    full: `${displayHour}:${minuteStr} ${period}`,
    short: `${displayHour}:${minuteStr}${period.toLowerCase()}`
  };
}

/**
 * Convert UTC time to local time and format it
 */
function formatLocalTime(utcHour: number, utcMinute: number): { full: string; short: string } {
  // Create a date in UTC for today
  const utcDate = new Date();
  utcDate.setUTCHours(utcHour, utcMinute, 0, 0);

  // Get local hour and minute
  const localHour = utcDate.getHours();
  const localMinute = utcDate.getMinutes();

  return formatTime(localHour, localMinute);
}

/**
 * Get day name from cron day of week
 */
function getDayName(dayOfWeek: string): string {
  const days: Record<string, string> = {
    '0': 'Sunday',
    '1': 'Monday',
    '2': 'Tuesday',
    '3': 'Wednesday',
    '4': 'Thursday',
    '5': 'Friday',
    '6': 'Saturday',
    '7': 'Sunday', // 7 is also Sunday in cron
    'SUN': 'Sunday',
    'MON': 'Monday',
    'TUE': 'Tuesday',
    'WED': 'Wednesday',
    'THU': 'Thursday',
    'FRI': 'Friday',
    'SAT': 'Saturday'
  };
  return days[dayOfWeek.toUpperCase()] || dayOfWeek;
}

/**
 * Calculate next run time from a cron expression
 * This is a simplified version - for production, consider using a library like cron-parser
 */
export function getNextRunTime(cronExpression: string | undefined | null): Date | null {
  if (!cronExpression) return null;

  const parts = cronExpression.split(' ');
  if (parts.length !== 5) return null;

  const [minute, hour] = parts;
  const now = new Date();

  // For daily schedules (simple case)
  if (minute !== '*' && hour !== '*' && parts[2] === '*' && parts[3] === '*' && parts[4] === '*') {
    const nextRun = new Date();
    nextRun.setUTCHours(parseInt(hour), parseInt(minute), 0, 0);

    // If the time has passed today, set to tomorrow
    if (nextRun <= now) {
      nextRun.setUTCDate(nextRun.getUTCDate() + 1);
    }

    return nextRun;
  }

  // For other patterns, return null (would need more complex logic)
  return null;
}

/**
 * Format time until next run
 */
export function formatTimeUntil(nextRun: Date | string | undefined | null): string {
  if (!nextRun) return '';

  const nextRunDate = typeof nextRun === 'string' ? new Date(nextRun) : nextRun;
  const now = new Date();
  const diffMs = nextRunDate.getTime() - now.getTime();

  if (diffMs < 0) return 'Now';

  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHrs = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays > 0) {
    return `in ${diffDays}d`;
  } else if (diffHrs > 0) {
    const mins = diffMins % 60;
    return mins > 0 ? `in ${diffHrs}h ${mins}m` : `in ${diffHrs}h`;
  } else if (diffMins > 0) {
    return `in ${diffMins}m`;
  } else {
    return 'in <1m';
  }
}
