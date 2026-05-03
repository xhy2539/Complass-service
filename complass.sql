-- MySQL dump 10.13  Distrib 8.0.41, for Win64 (x86_64)
--
-- Host: localhost    Database: complass
-- ------------------------------------------------------
-- Server version	8.0.41

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `comparison_risk_points`
--

DROP TABLE IF EXISTS `comparison_risk_points`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `comparison_risk_points` (
  `id` varchar(36) NOT NULL,
  `comparison_task_id` varchar(36) NOT NULL,
  `change_type` varchar(20) NOT NULL,
  `old_text` text,
  `new_text` text,
  `similarity` int DEFAULT NULL,
  `summary` text,
  `risk_level` enum('HIGH','MEDIUM','LOW') DEFAULT NULL,
  `suggestion` text,
  `old_position` json DEFAULT NULL,
  `new_position` json DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `category` varchar(50) DEFAULT NULL COMMENT '风险分类',
  `evidence` text COMMENT '证据材料',
  `impact` text COMMENT '影响程度',
  `source` varchar(20) DEFAULT 'coze',
  `status` varchar(20) NOT NULL DEFAULT 'pending',
  `confirmed_at` datetime DEFAULT NULL,
  `confirmed_by_user_id` varchar(36) DEFAULT NULL,
  `ignore_reason` text,
  PRIMARY KEY (`id`),
  KEY `ix_comparison_risk_points_comparison_task_id` (`comparison_task_id`),
  CONSTRAINT `comparison_risk_points_ibfk_1` FOREIGN KEY (`comparison_task_id`) REFERENCES `comparison_tasks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `comparison_tasks`
--

DROP TABLE IF EXISTS `comparison_tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `comparison_tasks` (
  `id` varchar(36) NOT NULL,
  `old_file_name` varchar(255) NOT NULL,
  `new_file_name` varchar(255) NOT NULL,
  `old_file_type` varchar(10) NOT NULL,
  `new_file_type` varchar(10) NOT NULL,
  `old_file_path` varchar(500) DEFAULT NULL,
  `new_file_path` varchar(500) DEFAULT NULL,
  `old_file_size` int DEFAULT NULL,
  `new_file_size` int DEFAULT NULL,
  `old_char_count` int DEFAULT NULL,
  `new_char_count` int DEFAULT NULL,
  `old_page_count` int DEFAULT NULL,
  `new_page_count` int DEFAULT NULL,
  `old_paragraph_count` int DEFAULT NULL,
  `new_paragraph_count` int DEFAULT NULL,
  `diff_stats` json DEFAULT NULL,
  `diff_details_json` json DEFAULT NULL,
  `position_info_json` json DEFAULT NULL,
  `coze_enhanced` json DEFAULT NULL,
  `total_risks` int DEFAULT NULL,
  `status` enum('PENDING','PROCESSING','COMPLETED','FAILED') NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  `user_id` varchar(36) DEFAULT NULL,
  `old_text` text COMMENT '旧合同完整纯文本',
  `new_text` text COMMENT '新合同完整纯文本',
  `old_sanitized_text` text COMMENT '旧合同脱敏后文本',
  `new_sanitized_text` text COMMENT '新合同脱敏后文本',
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `comparison_tasks_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `paragraphs`
--

DROP TABLE IF EXISTS `paragraphs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `paragraphs` (
  `id` varchar(36) NOT NULL,
  `review_task_id` varchar(36) NOT NULL,
  `index` int NOT NULL,
  `text` text,
  `char_offset_start` int DEFAULT NULL,
  `char_offset_end` int DEFAULT NULL,
  `page_number` int DEFAULT NULL,
  `is_key_clause` tinyint(1) DEFAULT '0',
  `paragraph_type` varchar(20) DEFAULT 'body',
  `paragraph_level` int DEFAULT '0',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `review_task_id` (`review_task_id`),
  CONSTRAINT `paragraphs_ibfk_1` FOREIGN KEY (`review_task_id`) REFERENCES `review_tasks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `review_tasks`
--

DROP TABLE IF EXISTS `review_tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `review_tasks` (
  `id` varchar(36) NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `file_type` varchar(10) NOT NULL,
  `file_path` varchar(500) DEFAULT NULL,
  `file_size` int DEFAULT NULL,
  `text` text,
  `char_count` int DEFAULT NULL,
  `page_count` int DEFAULT NULL,
  `paragraph_count` int DEFAULT NULL,
  `sentence_count` int DEFAULT NULL,
  `sanitized_text` text,
  `paragraphs_json` json DEFAULT NULL,
  `sentences_json` json DEFAULT NULL,
  `position_info_json` json DEFAULT NULL,
  `comparison_data_json` json DEFAULT NULL,
  `overall_conclusion` text,
  `risk_summary` json DEFAULT NULL,
  `suggest_deep_review` tinyint(1) DEFAULT NULL,
  `coze_message` text,
  `status` enum('PENDING','PROCESSING','COMPLETED','FAILED') NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  `user_id` varchar(36) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `review_tasks_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `risk_points`
--

DROP TABLE IF EXISTS `risk_points`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `risk_points` (
  `id` varchar(36) NOT NULL,
  `review_task_id` varchar(36) NOT NULL,
  `title` varchar(255) NOT NULL,
  `level` enum('HIGH','MEDIUM','LOW') NOT NULL,
  `reason` text,
  `suggestion` text,
  `position` json DEFAULT NULL,
  `original_text` text,
  `status` enum('PENDING','CONFIRMED','IGNORED') NOT NULL,
  `confirmed_at` datetime DEFAULT NULL,
  `confirmed_by` varchar(100) DEFAULT NULL,
  `ignore_reason` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `category` varchar(50) DEFAULT NULL,
  `evidence` text,
  `impact` text,
  `confirmed_by_user_id` varchar(36) DEFAULT NULL,
  `review_comment` text,
  `source` varchar(20) DEFAULT 'coze',
  PRIMARY KEY (`id`),
  KEY `ix_risk_points_review_task_id` (`review_task_id`),
  CONSTRAINT `risk_points_ibfk_1` FOREIGN KEY (`review_task_id`) REFERENCES `review_tasks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sentences`
--

DROP TABLE IF EXISTS `sentences`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sentences` (
  `id` varchar(36) NOT NULL,
  `review_task_id` varchar(36) NOT NULL,
  `index` int NOT NULL,
  `text` text,
  `char_offset_start` int DEFAULT NULL,
  `char_offset_end` int DEFAULT NULL,
  `paragraph_index` int DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `review_task_id` (`review_task_id`),
  CONSTRAINT `sentences_ibfk_1` FOREIGN KEY (`review_task_id`) REFERENCES `review_tasks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` varchar(36) NOT NULL,
  `email` varchar(255) NOT NULL,
  `nickname` varchar(100) NOT NULL,
  `hashed_password` varchar(255) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `is_verified` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `last_login_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-05-03 20:58:47
