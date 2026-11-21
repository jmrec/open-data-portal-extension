CREATE TABLE `resolved_outages` (
	`company_id` text DEFAULT 'beneco' NOT NULL,
	`outage_id` integer NOT NULL,
	`kind` text NOT NULL,
	`key` text NOT NULL,
	`fingerprint` text NOT NULL,
	`resolution` text NOT NULL,
	`resolved_at` integer NOT NULL,
	CONSTRAINT `resolved_outages_pk` PRIMARY KEY(`company_id`, `outage_id`)
);
--> statement-breakpoint
CREATE TABLE `beneco_barangays` (
	`id` integer PRIMARY KEY,
	`name` text NOT NULL,
	`municipality_id` integer NOT NULL,
	`pcode` text,
	`psgc` text,
	CONSTRAINT `fk_beneco_barangays_municipality_id_beneco_municipalities_id_fk` FOREIGN KEY (`municipality_id`) REFERENCES `beneco_municipalities`(`id`)
);
--> statement-breakpoint
CREATE TABLE `beneco_municipalities` (
	`id` integer PRIMARY KEY,
	`name` text NOT NULL,
	`pcode` text,
	`psgc` text
);
--> statement-breakpoint
CREATE INDEX `resolved_outages_resolved_at_idx` ON `resolved_outages` (`resolved_at`);