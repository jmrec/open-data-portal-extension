ALTER TABLE "beneco"."municipalities" ADD COLUMN IF NOT EXISTS "psgc" varchar(10);
--> statement-breakpoint
ALTER TABLE "beneco"."barangays" ADD COLUMN IF NOT EXISTS "psgc" varchar(10);
