import React, { useState, useRef, useEffect, type KeyboardEvent as ReactKeyboardEvent, type ChangeEvent } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChevronUp, ChevronDown, Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface CronExpressionInputProps {
  value: string;
  onChange: (value: string) => void;
}

// Define the structure of a cron field
interface CronField {
  name: string;
  min: number;
  max: number;
  allowedValues: string[];
  tooltip: string;
}

// Define the cron fields and their constraints
const cronFields: CronField[] = [
  {
    name: "minute",
    min: 0,
    max: 59,
    allowedValues: ["*", "/", "-", ","],
    tooltip: "Minute (0-59)",
  },
  {
    name: "hour",
    min: 0,
    max: 23,
    allowedValues: ["*", "/", "-", ","],
    tooltip: "Hour (0-23)",
  },
  {
    name: "day",
    min: 1,
    max: 31,
    allowedValues: ["*", "/", "-", ",", "?"],
    tooltip: "Day of month (1-31)",
  },
  {
    name: "month",
    min: 1,
    max: 12,
    allowedValues: ["*", "/", "-", ","],
    tooltip: "Month (1-12)",
  },
  {
    name: "weekday",
    min: 0,
    max: 6,
    allowedValues: ["*", "/", "-", ",", "?"],
    tooltip: "Day of week (0-6, 0=Sunday)",
  },
];

/**
 * Validates a cron expression
 * @param cronExpression The cron expression to validate
 * @returns True if the cron expression is valid, false otherwise
 */
export const isValidCronExpression = (cronExpression: string): boolean => {
  // Check if the expression has exactly 5 fields
  const fields = cronExpression.trim().split(/\s+/);
  if (fields.length !== 5) {
    return false;
  }

  // Validate each field
  return fields.every((field, index) => {
    const cronField = cronFields[index];

    // Check for asterisk (wildcard)
    if (field === "*") {
      return true;
    }

    // Check for step values (*/n or n/n)
    if (field.includes("/")) {
      const [base, step] = field.split("/");

      // Validate the step is a number
      if (!/^\d+$/.test(step)) {
        return false;
      }

      const stepNum = parseInt(step, 10);
      if (stepNum < 1) {
        return false;
      }

      // Validate the base
      if (base === "*") {
        return true;
      }

      if (!/^\d+$/.test(base)) {
        return false;
      }

      const baseNum = parseInt(base, 10);
      return baseNum >= cronField.min && baseNum <= cronField.max;
    }

    // Check for ranges (n-m)
    if (field.includes("-")) {
      const [start, end] = field.split("-");

      // Validate start and end are numbers
      if (!/^\d+$/.test(start) || !/^\d+$/.test(end)) {
        return false;
      }

      const startNum = parseInt(start, 10);
      const endNum = parseInt(end, 10);

      return (
        startNum >= cronField.min &&
        startNum <= cronField.max &&
        endNum >= cronField.min &&
        endNum <= cronField.max &&
        startNum <= endNum
      );
    }

    // Check for lists (n,m,o)
    if (field.includes(",")) {
      return field.split(",").every(item => {
        if (!/^\d+$/.test(item)) {
          return false;
        }

        const num = parseInt(item, 10);
        return num >= cronField.min && num <= cronField.max;
      });
    }

    // Check for single values
    if (!/^\d+$/.test(field)) {
      return field === "?"; // Allow ? for day-of-month and day-of-week
    }

    const num = parseInt(field, 10);
    return num >= cronField.min && num <= cronField.max;
  });
};

export function CronExpressionInput({ value, onChange }: CronExpressionInputProps) {
  // Split the cron expression into fields
  const [fields, setFields] = useState<string[]>(
    value ? value.split(" ") : ["*", "*", "*", "*", "*"]
  );
  const [isValid, setIsValid] = useState<boolean>(true);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const lastPropValue = useRef(value);

  // Update fields when value changes externally
  useEffect(() => {
    if (value !== lastPropValue.current) {
      const newFields = value ? value.split(" ") : ["*", "*", "*", "*", "*"];
      setFields(newFields);
      setIsValid(isValidCronExpression(value));
      lastPropValue.current = value;
    }
  }, [value]);

  // Update the parent component when fields change
  useEffect(() => {
    const newValue = fields.join(" ");
    setIsValid(isValidCronExpression(newValue));

    // Only call onChange if the value actually changed from what's in props
    if (newValue !== lastPropValue.current) {
      lastPropValue.current = newValue;
      onChange(newValue);
    }
  }, [fields, onChange]);

  // Handle input change for a specific field
  const handleFieldChange = (index: number, e: ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value;

    // Only allow valid characters for this field
    const field = cronFields[index];
    const validChars = [...field.allowedValues, ...Array.from({ length: 10 }, (_, i) => i.toString())];

    // Check if all characters are valid
    const isValid = [...newValue].every(char => validChars.includes(char));

    if (isValid) {
      const newFields = [...fields];
      newFields[index] = newValue;
      setFields(newFields);
    }
  };

  // Handle key down events for navigation and special keys
  const handleKeyDown = (index: number, e: ReactKeyboardEvent<HTMLInputElement>) => {
    const field = cronFields[index];
    const currentValue = fields[index];

    // Handle backspace to replace with asterisk when field is emptied
    if (e.key === "Backspace" && currentValue.length === 1) {
      e.preventDefault();
      const newFields = [...fields];
      newFields[index] = "*";
      setFields(newFields);
      return;
    }

    // Handle arrow keys for incrementing/decrementing numeric values
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();

      // Only increment/decrement if the field is a single number
      if (/^\d+$/.test(currentValue)) {
        let num = parseInt(currentValue, 10);

        if (e.key === "ArrowUp") {
          num = num >= field.max ? field.min : num + 1;
        } else {
          num = num <= field.min ? field.max : num - 1;
        }

        const newFields = [...fields];
        newFields[index] = num.toString();
        setFields(newFields);
      }
      return;
    }

    // Handle tab and arrow keys for navigation between fields
    if (e.key === "ArrowRight" && e.currentTarget.selectionStart === currentValue.length) {
      e.preventDefault();
      const nextIndex = index < cronFields.length - 1 ? index + 1 : 0;
      inputRefs.current[nextIndex]?.focus();
      return;
    }

    if (e.key === "ArrowLeft" && e.currentTarget.selectionStart === 0) {
      e.preventDefault();
      const prevIndex = index > 0 ? index - 1 : cronFields.length - 1;
      inputRefs.current[prevIndex]?.focus();
      return;
    }
  };

  // Handle increment/decrement buttons
  const handleIncrement = (index: number) => {
    const field = cronFields[index];
    const currentValue = fields[index];

    if (currentValue === "*") {
      // If current value is *, change to min value
      const newFields = [...fields];
      newFields[index] = field.min.toString();
      setFields(newFields);
      return;
    }

    if (/^\d+$/.test(currentValue)) {
      let num = parseInt(currentValue, 10);
      num = num >= field.max ? field.min : num + 1;

      const newFields = [...fields];
      newFields[index] = num.toString();
      setFields(newFields);
    }
  };

  const handleDecrement = (index: number) => {
    const field = cronFields[index];
    const currentValue = fields[index];

    if (currentValue === "*") {
      // If current value is *, change to max value
      const newFields = [...fields];
      newFields[index] = field.max.toString();
      setFields(newFields);
      return;
    }

    if (/^\d+$/.test(currentValue)) {
      let num = parseInt(currentValue, 10);
      num = num <= field.min ? field.max : num - 1;

      const newFields = [...fields];
      newFields[index] = num.toString();
      setFields(newFields);
    }
  };

  return (
    <div className="space-y-2">
      <Label className="text-base font-medium">Cron Expression</Label>

      <div className="flex flex-col space-y-4">
        <div className="grid grid-cols-5 gap-2 bg-background border rounded-md p-4">
          {cronFields.map((field, index) => (
            <div key={field.name} className="flex flex-col">
              <div className="flex items-center mb-1">
                <Label htmlFor={`cron-${field.name}`} className="text-xs text-muted-foreground">
                  {field.name}
                </Label>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3 w-3 text-muted-foreground ml-1" />
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{field.tooltip}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div className="relative">
                <div className="flex flex-col">
                  <button
                    type="button"
                    className="absolute right-1 top-0 text-muted-foreground hover:text-foreground z-10"
                    onClick={() => handleIncrement(index)}
                  >
                    <ChevronUp className="h-4 w-4" />
                  </button>
                  <Input
                    id={`cron-${field.name}`}
                    ref={(el) => (inputRefs.current[index] = el)}
                    value={fields[index] || "*"}
                    onChange={(e) => handleFieldChange(index, e)}
                    onKeyDown={(e) => handleKeyDown(index, e)}
                    className={`font-mono text-center pr-6 ${!isValid ? "border-destructive" : ""} bg-black/90 text-white border-gray-800`}
                    maxLength={10}
                  />
                  <button
                    type="button"
                    className="absolute right-1 bottom-0 text-muted-foreground hover:text-foreground z-10"
                    onClick={() => handleDecrement(index)}
                  >
                    <ChevronDown className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="text-xs text-muted-foreground">
          <p>Format: minute hour day month weekday</p>
          <p>Example: "0 9 * * 1" for every Monday at 9 AM</p>
        </div>
      </div>
    </div>
  );
}
