-- ============================================================
-- 校园活动报名与管理系统 · 建表脚本
-- 执行方式：mysql -u root -p < database/schema.sql
-- 说明：脚本自带 CREATE DATABASE / USE，无需提前建库
-- ============================================================
CREATE DATABASE IF NOT EXISTS campus_events
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE campus_events;
SET FOREIGN_KEY_CHECKS=0;

--
-- Table structure for table `categories`
--

CREATE TABLE IF NOT EXISTS `categories` (
  `category_id` int NOT NULL AUTO_INCREMENT,
  `category_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `uk_category_name` (`category_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `comments`
--

CREATE TABLE IF NOT EXISTS `comments` (
  `comment_id` int NOT NULL AUTO_INCREMENT,
  `event_id` int NOT NULL,
  `user_id` int NOT NULL,
  `content` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`comment_id`),
  KEY `user_id` (`user_id`),
  KEY `idx_comments_event_created` (`event_id`, `created_at`),
  CONSTRAINT `comments_ibfk_1` FOREIGN KEY (`event_id`) REFERENCES `events` (`event_id`) ON DELETE CASCADE,
  CONSTRAINT `comments_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `event_categories`
--

CREATE TABLE IF NOT EXISTS `event_categories` (
  `event_id` int NOT NULL,
  `category_id` int NOT NULL,
  PRIMARY KEY (`event_id`,`category_id`),
  KEY `category_id` (`category_id`),
  CONSTRAINT `event_categories_ibfk_1` FOREIGN KEY (`event_id`) REFERENCES `events` (`event_id`) ON DELETE CASCADE,
  CONSTRAINT `event_categories_ibfk_2` FOREIGN KEY (`category_id`) REFERENCES `categories` (`category_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `events`
--

CREATE TABLE IF NOT EXISTS `events` (
  `event_id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `organizer_id` int NOT NULL,
  `venue_id` int NOT NULL,
  `start_time` datetime NOT NULL,
  `end_time` datetime NOT NULL,
  `capacity` int NOT NULL,
  `status` enum('open','closed') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'open',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`event_id`),
  KEY `idx_start_time` (`start_time`),
  KEY `idx_events_venue_time` (`venue_id`, `start_time`, `end_time`),
  KEY `idx_events_org_start` (`organizer_id`, `start_time`),
  CONSTRAINT `events_ibfk_1` FOREIGN KEY (`organizer_id`) REFERENCES `users` (`user_id`),
  CONSTRAINT `events_ibfk_2` FOREIGN KEY (`venue_id`) REFERENCES `venues` (`venue_id`),
  CONSTRAINT `events_chk_capacity` CHECK (`capacity` > 0),
  CONSTRAINT `events_chk_time` CHECK (`end_time` > `start_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `registrations`
--

CREATE TABLE IF NOT EXISTS `registrations` (
  `registration_id` int NOT NULL AUTO_INCREMENT,
  `student_id` int NOT NULL,
  `event_id` int NOT NULL,
  `status` enum('registered','cancelled','checked_in') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'registered',
  `registered_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `check_in_time` datetime DEFAULT NULL,
  `cancelled_at` datetime DEFAULT NULL,
  `cancelled_by` int DEFAULT NULL,
  `updated_at`  datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`registration_id`),
  UNIQUE KEY `uk_student_event` (`student_id`,`event_id`),
  KEY `idx_reg_event_status` (`event_id`,`status`),
  KEY `idx_reg_cancelled_by` (`cancelled_by`),
  CONSTRAINT `registrations_ibfk_1` FOREIGN KEY (`student_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `registrations_ibfk_2` FOREIGN KEY (`event_id`) REFERENCES `events` (`event_id`) ON DELETE CASCADE,
  CONSTRAINT `registrations_ibfk_3` FOREIGN KEY (`cancelled_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `users`
--

CREATE TABLE IF NOT EXISTS `users` (
  `user_id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password_hash` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` enum('student','organizer','admin') COLLATE utf8mb4_unicode_ci DEFAULT 'student',
  -- token_version：登出 / 改密码时 +1，使所有已签发的旧令牌立即失效
  `token_version` int NOT NULL DEFAULT 0,
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Table structure for table `venues`
--

CREATE TABLE IF NOT EXISTS `venues` (
  `venue_id` int NOT NULL AUTO_INCREMENT,
  `venue_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `location` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `capacity` int NOT NULL,
  `available_status` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`venue_id`),
  UNIQUE KEY `uk_venue_name` (`venue_name`),
  CONSTRAINT `venues_chk_capacity`  CHECK (`capacity` > 0),
  CONSTRAINT `venues_chk_available` CHECK (`available_status` IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Dumping data for table `categories`
--

-- 种子数据用 8.0.19+ 的行别名写法（VALUES() 函数自 8.0.20 起已弃用）
INSERT INTO `categories` (`category_name`, `description`) VALUES
('学术讲座','学术类讲座、报告'),
('文体活动','文艺、体育类活动'),
('志愿服务','志愿服务与社会实践'),
('竞赛比赛','各类竞赛与比赛') AS new
ON DUPLICATE KEY UPDATE
  `description` = new.`description`;

INSERT INTO `venues` (`venue_name`, `location`, `capacity`, `available_status`) VALUES
('大学生活动中心','校园东区',200,1),
('图书馆报告厅','图书馆二楼',300,1),
('体育馆','校园北区',500,1),
('教学楼A101','教学区A栋',120,1),
('操场','校园西区',1000,1) AS new
ON DUPLICATE KEY UPDATE
  `location`         = new.`location`,
  `capacity`         = new.`capacity`,
  `available_status` = new.`available_status`;

SET FOREIGN_KEY_CHECKS=1;

-- ============================================================
-- 数据库端对象：视图 / 触发器 / 存储过程
-- 这些对象把一部分一致性保证和聚合逻辑放到数据库里，应用层只是调用方
-- 全部写成幂等形式（CREATE OR REPLACE / DROP IF EXISTS），重复执行不会报错
-- ============================================================

-- 视图：活动总览（报名数 / 签到数 / 余量 / 开始与结束状态一次算完，
-- 避免应用里重复写多份相关子查询，也让统计类查询有统一入口）
CREATE OR REPLACE VIEW `v_event_overview` AS
SELECT e.`event_id`, e.`title`, e.`description`, e.`organizer_id`, e.`venue_id`,
       e.`start_time`, e.`end_time`, e.`capacity`, e.`status`, e.`updated_at`,
       v.`venue_name`, v.`location` AS `venue_location`,
       v.`capacity` AS `venue_capacity`, u.`name` AS `organizer_name`,
       (e.`start_time` < NOW()) AS `started`,
       (e.`end_time` IS NOT NULL AND e.`end_time` < NOW()) AS `ended`,
       -- SUM() 在 MySQL 里返回 DECIMAL，Flask 会把它序列化成字符串，
       -- 所以显式 CAST 回整数，保证接口里的计数都是 JSON number
       CAST(COALESCE(s.`active_regs`, 0) AS SIGNED) AS `registered_count`,
       CAST(COALESCE(s.`checked_in`, 0) AS SIGNED) AS `checked_in_count`,
       CAST(GREATEST(e.`capacity` - COALESCE(s.`active_regs`, 0), 0) AS SIGNED) AS `remaining`
  FROM `events` e
  LEFT JOIN `venues` v ON e.`venue_id` = v.`venue_id`
  LEFT JOIN `users` u ON e.`organizer_id` = u.`user_id`
  LEFT JOIN (SELECT `event_id`,
                    SUM(`status` <> 'cancelled') AS `active_regs`,
                    SUM(`status` = 'checked_in') AS `checked_in`
               FROM `registrations`
              GROUP BY `event_id`) s ON s.`event_id` = e.`event_id`;

-- 触发器 1：场地时间段不得重叠、名额不得超过场地容量
-- 应用层已经校验过，这里是数据库自己字面守住的那一道：绕过接口直接写库、
-- 批处理导入、以后的维护脚本都拦得住。
-- 注意：触发器里不能对正在写入的同一张表做锁定读（MySQL 报 1442），
-- 所以这里的重叠检测是普通一致性读；并发下的串行化仍由应用层
-- SELECT ... FROM venues FOR UPDATE 的行锁保证，两者分工不同。
DROP TRIGGER IF EXISTS `trg_events_check_venue_bi`;
DROP TRIGGER IF EXISTS `trg_events_check_venue_bu`;

DELIMITER $$
CREATE TRIGGER `trg_events_check_venue_bi` BEFORE INSERT ON `events`
FOR EACH ROW
BEGIN
    DECLARE v_venue_capacity INT DEFAULT NULL;
    DECLARE v_conflict_id    INT DEFAULT NULL;

    SELECT MAX(`capacity`) INTO v_venue_capacity
      FROM `venues` WHERE `venue_id` = NEW.`venue_id`;
    IF v_venue_capacity IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '场地不存在';
    END IF;
    IF NEW.`capacity` > v_venue_capacity THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '名额超过场地容量（数据库触发器拦截）';
    END IF;

    SELECT MAX(`event_id`) INTO v_conflict_id
      FROM `events`
     WHERE `venue_id` = NEW.`venue_id`
       AND `start_time` < NEW.`end_time`
       AND `end_time`   > NEW.`start_time`;
    IF v_conflict_id IS NOT NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '该场地在该时间段已被占用（数据库触发器拦截）';
    END IF;
END$$
DELIMITER ;

DELIMITER $$
CREATE TRIGGER `trg_events_check_venue_bu` BEFORE UPDATE ON `events`
FOR EACH ROW
BEGIN
    DECLARE v_venue_capacity INT DEFAULT NULL;
    DECLARE v_conflict_id    INT DEFAULT NULL;

    SELECT MAX(`capacity`) INTO v_venue_capacity
      FROM `venues` WHERE `venue_id` = NEW.`venue_id`;
    IF v_venue_capacity IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '场地不存在';
    END IF;
    IF NEW.`capacity` > v_venue_capacity THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '名额超过场地容量（数据库触发器拦截）';
    END IF;

    SELECT MAX(`event_id`) INTO v_conflict_id
      FROM `events`
     WHERE `venue_id` = NEW.`venue_id`
       AND `event_id` <> NEW.`event_id`
       AND `start_time` < NEW.`end_time`
       AND `end_time`   > NEW.`start_time`;
    IF v_conflict_id IS NOT NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '该场地在该时间段已被占用（数据库触发器拦截）';
    END IF;
END$$
DELIMITER ;

-- 触发器 2：报名状态必须和对应时间戳一致
-- 防的是应用层 bug 或手工改库造成“状态=已签到但 check_in_time 为空”这种数字
DROP TRIGGER IF EXISTS `trg_registrations_status_bi`;
DROP TRIGGER IF EXISTS `trg_registrations_status_bu`;

DELIMITER $$
CREATE TRIGGER `trg_registrations_status_bi` BEFORE INSERT ON `registrations`
FOR EACH ROW
BEGIN
    IF (NEW.`status` = 'checked_in') <> (NEW.`check_in_time` IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '报名状态与签到时间不一致';
    END IF;
    IF (NEW.`status` = 'cancelled') <> (NEW.`cancelled_at` IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '报名状态与取消时间不一致';
    END IF;
    IF NEW.`status` = 'cancelled' AND NEW.`cancelled_by` IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '取消报名必须记录操作人';
    END IF;
END$$
DELIMITER ;

DELIMITER $$
CREATE TRIGGER `trg_registrations_status_bu` BEFORE UPDATE ON `registrations`
FOR EACH ROW
BEGIN
    IF (NEW.`status` = 'checked_in') <> (NEW.`check_in_time` IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '报名状态与签到时间不一致';
    END IF;
    IF (NEW.`status` = 'cancelled') <> (NEW.`cancelled_at` IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '报名状态与取消时间不一致';
    END IF;
    IF NEW.`status` = 'cancelled' AND NEW.`cancelled_by` IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '取消报名必须记录操作人';
    END IF;
END$$
DELIMITER ;

-- 存储过程：单个活动的出入率报告（聚合逻辑放在数据库里，接口直接 CALL）
DROP PROCEDURE IF EXISTS `sp_event_attendance`;

DELIMITER $$
CREATE PROCEDURE `sp_event_attendance`(IN p_event_id INT)
BEGIN
    SELECT e.`event_id`, e.`title`, e.`capacity`, e.`start_time`, e.`end_time`,
           COALESCE(SUM(r.`status` <> 'cancelled'), 0)               AS `active_regs`,
           COALESCE(SUM(r.`status` = 'checked_in'), 0)               AS `checked_in`,
           COALESCE(SUM(r.`status` = 'cancelled'), 0)                AS `cancelled`,
           ROUND(SUM(r.`status` = 'checked_in')
                 / NULLIF(SUM(r.`status` <> 'cancelled'), 0) * 100, 1) AS `attendance_pct`,
           ROUND(SUM(r.`status` <> 'cancelled')
                 / NULLIF(e.`capacity`, 0) * 100, 1)                  AS `fill_pct`
      FROM `events` e
      LEFT JOIN `registrations` r ON r.`event_id` = e.`event_id`
     WHERE e.`event_id` = p_event_id
     GROUP BY e.`event_id`, e.`title`, e.`capacity`, e.`start_time`, e.`end_time`;
END$$
DELIMITER ;