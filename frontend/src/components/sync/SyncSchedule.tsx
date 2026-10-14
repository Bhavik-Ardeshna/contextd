import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ClockIcon, ZapIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { CronExpressionInput, isValidCronExpression } from "./CronExpressionInput";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

// Custom Number1Icon component
const Number1Icon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex items-center justify-center", className)}>
    <span className="font-bold text-2xl leading-none">1</span>
  </div>
);

export interface SyncScheduleConfig {
  type: "one-time" | "scheduled";
  frequency?: "hourly" | "daily" | "weekly" | "monthly" | "custom";
  hour?: number;
  minute?: number;
  dayOfWeek?: number;
  dayOfMonth?: number;
  cronExpression?: string;
}

interface SyncScheduleProps {
  value: SyncScheduleConfig;
  onChange: (config: SyncScheduleConfig) => void;
}

/**
 * Converts the UI schedule configuration to a cron expression
 */
export const buildCronExpression = (config: SyncScheduleConfig): string | null => {
  if (config.type !== "scheduled") return null;

  const { frequency, hour, minute, dayOfWeek, dayOfMonth, cronExpression } = config;

  // If using custom cron expression, use as-is
  if (frequency === "custom" && cronExpression) {
    return cronExpression;
  }

  // Convert local time to UTC time for storage
  let utcMinute = minute || 0;
  let utcHour = hour || 0;

  // No need to convert if hour is not used (hourly frequency)
  if (frequency !== "hourly" && hour !== undefined) {
    // The hour value is already in UTC from the dropdown selection, no need to convert again
    utcHour = hour;
    utcMinute = minute || 0;
  }

  switch (frequency) {
    case "hourly":
      return `${utcMinute} * * * *`; // At the specified minute of every hour
    case "daily":
      return `${utcMinute} ${utcHour} * * *`; // At the specified time every day
    case "weekly":
      return `${utcMinute} ${utcHour} * * ${dayOfWeek || 1}`; // Specified time on specified day of week
    case "monthly":
      return `${utcMinute} ${utcHour} ${dayOfMonth || 1} * *`; // Specified time on specified day of month
    default:
      return "0 9 * * *"; // Default to daily at 9:00 AM UTC
  }
};

export function SyncSchedule({ value, onChange }: SyncScheduleProps) {
  const [activeType, setActiveType] = useState<"one-time" | "scheduled">(value.type);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Sync activeType with prop changes
  React.useEffect(() => {
    setActiveType(value.type);
  }, [value.type]);

  const handleTypeChange = (type: "one-time" | "scheduled") => {
    setActiveType(type);

    // Clean config when switching to one-time
    const newConfig: SyncScheduleConfig = type === "one-time"
      ? { type: "one-time" }
      : {
        type: "scheduled",
        frequency: value.frequency || "daily",
        hour: value.hour,
        minute: value.minute,
        dayOfWeek: value.dayOfWeek,
        dayOfMonth: value.dayOfMonth,
        cronExpression: value.cronExpression
      };

    onChange(newConfig);
  };

  const handleFrequencyChange = (frequency: string) => {
    // Initialize default cronExpression for custom frequency
    const newConfig = {
      ...value,
      frequency: frequency as SyncScheduleConfig["frequency"]
    };

    if (frequency === "custom" && !value.cronExpression) {
      newConfig.cronExpression = "* * * * *";
    }

    onChange(newConfig);
    setValidationError(null);
  };

  const handleTimeChange = (field: string, fieldValue: string | number) => {
    onChange({
      ...value,
      [field]: fieldValue
    });
    setValidationError(null);
  };

  // Validate cron expression if needed
  const isCronValid = () => {
    if (value.type === "scheduled" && value.frequency === "custom" && value.cronExpression) {
      return isValidCronExpression(value.cronExpression);
    }
    return true;
  };

  return (
    <Card className="bg-background border-none">
      <CardContent className="pt-6 space-y-6">
        {/* Main options as clickable cards */}
        <div className="grid grid-cols-3 gap-4">
          <div
            className={cn(
              "group cursor-pointer rounded-lg border p-5 transition-all hover:bg-accent hover:shadow-sm",
              activeType === "one-time" ? "bg-accent border-primary" : "bg-card border-muted"
            )}
            onClick={() => handleTypeChange("one-time")}
          >
            <div className="flex items-center justify-center h-12 w-12 rounded-full bg-background border mb-3 mx-auto group-hover:bg-muted">
              <Number1Icon className="text-primary" />
            </div>
            <h3 className="text-center font-medium mb-1">One-time sync</h3>
            <p className="text-center text-sm text-muted-foreground">
              Manual sync triggered on demand
            </p>
          </div>

          <div
            className={cn(
              "group cursor-pointer rounded-lg border p-5 transition-all hover:bg-accent hover:shadow-sm",
              activeType === "scheduled" ? "bg-accent border-primary" : "bg-card border-muted"
            )}
            onClick={() => handleTypeChange("scheduled")}
          >
            <div className="flex items-center justify-center h-12 w-12 rounded-full bg-background border mb-3 mx-auto group-hover:bg-muted">
              <ClockIcon className="h-6 w-6 text-primary" />
            </div>
            <h3 className="text-center font-medium mb-1">Scheduled sync</h3>
            <p className="text-center text-sm text-muted-foreground">
              Automatic recurring sync
            </p>
          </div>

          {/* New "Instant Update" card that's disabled */}
          <div
            className="group relative rounded-lg border p-5 bg-muted/10 border-dashed"
          >
            {/* PRO badge */}
            <div className="absolute top-2 right-2 bg-primary/40 text-primary-foreground text-xs font-bold py-1 px-2 rounded-full shadow-sm">
              PRO
            </div>
            <div className="flex items-center justify-center h-12 w-12 rounded-full bg-background border mb-3 mx-auto">
              <ZapIcon className="h-6 w-6 text-muted-foreground" />
            </div>
            <h3 className="text-center font-medium mb-1 text-muted-foreground">Instant Update</h3>
            <p className="text-center text-sm text-muted-foreground">
              Webhook-based real-time updates
            </p>
            <div className="mt-2 bg-muted/30 py-1 px-2 rounded text-xs text-center font-medium text-muted-foreground">
              Coming soon
            </div>
          </div>
        </div>

        {/* Scheduled sync options */}
        <AnimatePresence>
          {activeType === "scheduled" && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="pt-3 space-y-6">
                {/* Frequency options */}
                <RadioGroup
                  value={value.frequency || "daily"}
                  onValueChange={handleFrequencyChange}
                  className="flex justify-center space-x-4"
                >
                  <div className="flex items-center space-x-1">
                    <RadioGroupItem value="hourly" id="hourly" />
                    <Label htmlFor="hourly" className="cursor-pointer">Hourly</Label>
                  </div>
                  <div className="flex items-center space-x-1">
                    <RadioGroupItem value="daily" id="daily" />
                    <Label htmlFor="daily" className="cursor-pointer">Daily</Label>
                  </div>
                  <div className="flex items-center space-x-1">
                    <RadioGroupItem value="weekly" id="weekly" />
                    <Label htmlFor="weekly" className="cursor-pointer">Weekly</Label>
                  </div>
                  <div className="flex items-center space-x-1">
                    <RadioGroupItem value="monthly" id="monthly" />
                    <Label htmlFor="monthly" className="cursor-pointer">Monthly</Label>
                  </div>
                  <div className="flex items-center space-x-1">
                    <RadioGroupItem value="custom" id="custom" />
                    <Label htmlFor="custom" className="cursor-pointer">Custom</Label>
                  </div>
                </RadioGroup>

                {/* Time settings based on frequency */}
                <div className="space-y-4 pb-2">
                  {value.frequency === "hourly" && (
                    <div className="flex items-center gap-2 justify-center">
                      <Label htmlFor="minute" className="min-w-24 text-right">At minute:</Label>
                      <Select
                        value={String(value.minute || 0)}
                        onValueChange={(val) => handleTimeChange("minute", parseInt(val))}
                      >
                        <SelectTrigger id="minute" className="w-[120px]">
                          <SelectValue placeholder="Minute" />
                        </SelectTrigger>
                        <SelectContent>
                          {Array.from({ length: 60 }).map((_, i) => (
                            <SelectItem key={i} value={String(i)}>
                              {i.toString().padStart(2, '0')}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {(value.frequency === "daily" || value.frequency === "weekly" || value.frequency === "monthly") && (
                    <div className="flex gap-6 justify-center">
                      <div className="flex items-center gap-2">
                        <Label htmlFor="hour" className="min-w-16 text-right">Hour:</Label>
                        <Select
                          value={String(value.hour || 0)}
                          onValueChange={(val) => handleTimeChange("hour", parseInt(val))}
                        >
                          <SelectTrigger id="hour" className="w-[140px]">
                            <SelectValue placeholder="Hour" />
                          </SelectTrigger>
                          <SelectContent>
                            {Array.from({ length: 24 }).map((_, i) => {
                              // What user sees is local time (i), but we store the corresponding UTC value
                              const localHour = i;
                              // Convert local to UTC by subtracting the timezone offset
                              const tzOffsetHours = new Date().getTimezoneOffset() / 60; // This will be positive for UTC+
                              const utcHour = (localHour + tzOffsetHours + 24) % 24;

                              return (
                                <SelectItem key={i} value={String(utcHour)}>
                                  {localHour.toString().padStart(2, '0')}:00
                                </SelectItem>
                              );
                            })}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex items-center gap-2">
                        <Label htmlFor="minute" className="min-w-16 text-right">Minute:</Label>
                        <Select
                          value={String(value.minute || 0)}
                          onValueChange={(val) => handleTimeChange("minute", parseInt(val))}
                        >
                          <SelectTrigger id="minute" className="w-[120px]">
                            <SelectValue placeholder="Minute" />
                          </SelectTrigger>
                          <SelectContent>
                            {Array.from({ length: 60 }).map((_, i) => (
                              <SelectItem key={i} value={String(i)}>
                                {i.toString().padStart(2, '0')}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  )}

                  {value.frequency === "weekly" && (
                    <div className="flex items-center gap-2 justify-center mt-3">
                      <Label htmlFor="dayOfWeek" className="min-w-24 text-right">Day of week:</Label>
                      <Select
                        value={String(value.dayOfWeek || 1)}
                        onValueChange={(val) => handleTimeChange("dayOfWeek", parseInt(val))}
                      >
                        <SelectTrigger id="dayOfWeek" className="w-[180px]">
                          <SelectValue placeholder="Select day" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="1">Monday</SelectItem>
                          <SelectItem value="2">Tuesday</SelectItem>
                          <SelectItem value="3">Wednesday</SelectItem>
                          <SelectItem value="4">Thursday</SelectItem>
                          <SelectItem value="5">Friday</SelectItem>
                          <SelectItem value="6">Saturday</SelectItem>
                          <SelectItem value="0">Sunday</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {value.frequency === "monthly" && (
                    <div className="flex items-center gap-2 justify-center mt-3">
                      <Label htmlFor="dayOfMonth" className="min-w-24 text-right">Day of month:</Label>
                      <Select
                        value={String(value.dayOfMonth || 1)}
                        onValueChange={(val) => handleTimeChange("dayOfMonth", parseInt(val))}
                      >
                        <SelectTrigger id="dayOfMonth" className="w-[120px]">
                          <SelectValue placeholder="Select day" />
                        </SelectTrigger>
                        <SelectContent>
                          {Array.from({ length: 31 }).map((_, i) => (
                            <SelectItem key={i} value={String(i + 1)}>
                              {i + 1}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {value.frequency === "custom" && (
                    <div className="max-w-xl mx-auto mt-3">
                      <div className="rounded-lg bg-muted p-4">
                        <CronExpressionInput
                          value={value.cronExpression || "* * * * *"}
                          onChange={(cronExp) => handleTimeChange("cronExpression", cronExp)}
                        />
                        {validationError && (
                          <p className="text-xs text-destructive mt-1">{validationError}</p>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Show the generated cron expression for user reference */}
                  {value.frequency !== "custom" && (
                    <div className="rounded-md bg-muted p-3 max-w-md mx-auto mt-6 text-center">
                      <p className="text-xs text-muted-foreground">
                        Cron expression: <code className="font-mono">{buildCronExpression(value)}</code>
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

      </CardContent>
    </Card>
  );
}

// Re-export isValidCronExpression so it can be imported by other components
export { isValidCronExpression };
