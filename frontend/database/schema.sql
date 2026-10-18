-- ============================================================
-- 校园活动报名与管理系统 - 数据库建表脚本（修改版）
-- 适用：MySQL 8.0.16+（依赖 CHECK 约束）
--
-- 相对原始版本的改动：
--   1. 补齐 NOT NULL 约束，避免出现「无时间/无名额」的活动。
--   2. events.status 与 registrations.status 改为 enum，取值受限。
--   3. 增加 CHECK (end_time > start_time)、CHECK (capacity > 0)。
--   4. 外键统一加上 ON DELETE CASCADE / RESTRICT，删除活动可自动清理关联数据。
--   5. 补充索引与外键索引，改善查询性能。
-- ============================================================

CREATE DATABASE IF NOT EXISTS `campus_events`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `campus_events`;

-- 先按依赖倒序删除旧表，方便重复执行
DROP TABLE IF EXISTS `comments`;
DROP TABLE IF EXISTS `event_categories`;
DROP TABLE IF EXISTS `registrations`;
DROP TABLE IF EXISTS `events`;
DROP TABLE IF EXISTS `categories`;
DROP TABLE IF EXISTS `venues`;
DROP TABLE IF EXISTS `users`;

-- ---------------- 用户表 ----------------
CREATE TABLE `users` (
  `user_id`       INT NOT NULL AUTO_INCREMENT,
  `name`          VARCHAR(100) NOT NULL,
  `email`         VARCHAR(100) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `role`          ENUM('student','organizer','admin') NOT NULL DEFAULT 'student',
  `created_at`    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uk_users_email` (`email`),
  KEY `idx_users_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 场地表 ----------------
CREATE TABLE `venues` (
  `venue_id`         INT NOT NULL AUTO_INCREMENT,
  `venue_name`       VARCHAR(100) NOT NULL,
  `location`         VARCHAR(255) DEFAULT NULL,
  `capacity`         INT DEFAULT NULL,
  `available_status` TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`venue_id`),
  CONSTRAINT `chk_venues_capacity` CHECK (`capacity` IS NULL OR `capacity` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 分类表 ----------------
CREATE TABLE `categories` (
  `category_id`   INT NOT NULL AUTO_INCREMENT,
  `category_name` VARCHAR(100) NOT NULL,
  `description`   TEXT,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `uk_categories_name` (`category_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 活动表 ----------------
CREATE TABLE `events` (
  `event_id`     INT NOT NULL AUTO_INCREMENT,
  `title`        VARCHAR(200) NOT NULL,
  `description`  TEXT,
  `organizer_id` INT NOT NULL,
  `venue_id`     INT NOT NULL,
  `start_time`   DATETIME NOT NULL,
  `end_time`     DATETIME NOT NULL,
  `capacity`     INT NOT NULL,
  `status`       ENUM('open','closed','cancelled') NOT NULL DEFAULT 'open',
  PRIMARY KEY (`event_id`),
  KEY `idx_events_organizer` (`organizer_id`),
  KEY `idx_events_venue` (`venue_id`),
  KEY `idx_events_start_time` (`start_time`),
  CONSTRAINT `fk_events_organizer` FOREIGN KEY (`organizer_id`)
    REFERENCES `users` (`user_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_events_venue` FOREIGN KEY (`venue_id`)
    REFERENCES `venues` (`venue_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `chk_events_time` CHECK (`end_time` > `start_time`),
  CONSTRAINT `chk_events_capacity` CHECK (`capacity` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 活动-分类关联表 ----------------
CREATE TABLE `event_categories` (
  `event_id`    INT NOT NULL,
  `category_id` INT NOT NULL,
  PRIMARY KEY (`event_id`, `category_id`),
  KEY `idx_event_categories_category` (`category_id`),
  CONSTRAINT `fk_ec_event` FOREIGN KEY (`event_id`)
    REFERENCES `events` (`event_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_ec_category` FOREIGN KEY (`category_id`)
    REFERENCES `categories` (`category_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 报名表 ----------------
CREATE TABLE `registrations` (
  `registration_id` INT NOT NULL AUTO_INCREMENT,
  `student_id`      INT NOT NULL,
  `event_id`        INT NOT NULL,
  `registered_at`   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status`          ENUM('registered','cancelled','checked_in') NOT NULL DEFAULT 'registered',
  `check_in_time`   DATETIME DEFAULT NULL,
  PRIMARY KEY (`registration_id`),
  -- 同一学生对同一活动只能有一条记录（取消后重新报名走 UPDATE）
  UNIQUE KEY `uk_student_event` (`student_id`, `event_id`),
  KEY `idx_registrations_event` (`event_id`),
  KEY `idx_registrations_status` (`event_id`, `status`),
  CONSTRAINT `fk_registrations_student` FOREIGN KEY (`student_id`)
    REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_registrations_event` FOREIGN KEY (`event_id`)
    REFERENCES `events` (`event_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------- 评论表 ----------------
CREATE TABLE `comments` (
  `comment_id` INT NOT NULL AUTO_INCREMENT,
  `event_id`   INT NOT NULL,
  `user_id`    INT NOT NULL,
  `content`    TEXT NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`comment_id`),
  KEY `idx_comments_event` (`event_id`),
  KEY `idx_comments_user` (`user_id`),
  CONSTRAINT `fk_comments_event` FOREIGN KEY (`event_id`)
    REFERENCES `events` (`event_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_comments_user` FOREIGN KEY (`user_id`)
    REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- 可选：基础场地与分类数据（不需要可整段删除）
-- ============================================================
INSERT INTO `venues` (`venue_name`, `location`, `capacity`, `available_status`) VALUES
  ('大学生活动中心报告厅', '东区活动中心 1 楼', 200, 1),
  ('第三教学楼 301 教室', '第三教学楼 3 楼', 60, 1),
  ('图书馆学术报告厅', '图书馆 2 楼', 120, 1),
  ('体育馆多功能厅', '体育馆西侧', 300, 1);

INSERT INTO `categories` (`category_name`, `description`) VALUES
  ('学术讲座', '各类学术报告与讲座'),
  ('文艺活动', '演出、晚会、比赛等'),
  ('体育竞技', '运动会、球类比赛等'),
  ('志愿服务', '志愿与公益活动');
