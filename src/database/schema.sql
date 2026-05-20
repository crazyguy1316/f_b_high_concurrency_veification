-- DDL Schema for Ticketing Verification System
-- Engine: MySQL 8.0

CREATE DATABASE IF NOT EXISTS `ticketing_db` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `ticketing_db`;

CREATE TABLE IF NOT EXISTS `orders` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `member_id` INT NOT NULL,
    `event_id` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_member_id` (`member_id`),
    INDEX `idx_event_id` (`event_id`),
    UNIQUE KEY `uk_member_event` (`member_id`, `event_id`)
) ENGINE=InnoDB;
