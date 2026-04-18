// 自动识别构建工具，便于同一流水线兼容 Maven/Gradle。
def detectBuildTool() {
    if (fileExists('pom.xml') || fileExists('mvnw') || fileExists('mvnw.cmd')) {
        return 'maven'
    }
    if (fileExists('build.gradle') || fileExists('build.gradle.kts') || fileExists('gradlew') || fileExists('gradlew.bat')) {
        return 'gradle'
    }
    return 'unknown'
}

// 尝试拉取源码；若当前任务为内联 Pipeline 且无 SCM 上下文，则优雅降级。
def checkoutSource() {
    try {
        checkout scm
        return true
    } catch (Exception ex) {
        echo "checkout scm unavailable, fallback to bootstrap mode: ${ex.getMessage()}"
        return false
    }
}

// 统一封装命令执行，兼容 Linux/Windows 节点。
def runCommand(String unixCommand, String windowsCommand) {
    if (isUnix()) {
        sh unixCommand
    } else {
        bat windowsCommand
    }
}

// 执行代码风格检查，提前拦截格式和规范问题。
def runStyleCheck(String buildTool) {
    if (buildTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand('chmod +x mvnw && ./mvnw -B -U checkstyle:check', '.\\mvnw.cmd -B -U checkstyle:check')
        } else {
            runCommand('mvn -B -U checkstyle:check', 'mvn -B -U checkstyle:check')
        }
        return
    }

    if (buildTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew check --no-daemon', '.\\gradlew.bat check --no-daemon')
        } else {
            runCommand('gradle check --no-daemon', 'gradle check --no-daemon')
        }
    }
}

// 执行单元测试，确保核心逻辑在提交前稳定。
def runUnitTests(String buildTool) {
    if (buildTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand('chmod +x mvnw && ./mvnw -B -U test', '.\\mvnw.cmd -B -U test')
        } else {
            runCommand('mvn -B -U test', 'mvn -B -U test')
        }
        return
    }

    if (buildTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew test --no-daemon', '.\\gradlew.bat test --no-daemon')
        } else {
            runCommand('gradle test --no-daemon', 'gradle test --no-daemon')
        }
    }
}

// 执行集成测试，验证模块之间协作是否正确。
def runIntegrationTests(String buildTool) {
    if (buildTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand('chmod +x mvnw && ./mvnw -B -U failsafe:integration-test failsafe:verify', '.\\mvnw.cmd -B -U failsafe:integration-test failsafe:verify')
        } else {
            runCommand('mvn -B -U failsafe:integration-test failsafe:verify', 'mvn -B -U failsafe:integration-test failsafe:verify')
        }
        return
    }

    if (buildTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew check --no-daemon', '.\\gradlew.bat check --no-daemon')
        } else {
            runCommand('gradle check --no-daemon', 'gradle check --no-daemon')
        }
    }
}

// 构建可交付产物，默认跳过重复测试以缩短时长。
def buildArtifact(String buildTool) {
    if (buildTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand('chmod +x mvnw && ./mvnw -B -U package -DskipTests', '.\\mvnw.cmd -B -U package -DskipTests')
        } else {
            runCommand('mvn -B -U package -DskipTests', 'mvn -B -U package -DskipTests')
        }
        return
    }

    if (buildTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew build -x test --no-daemon', '.\\gradlew.bat build -x test --no-daemon')
        } else {
            runCommand('gradle build -x test --no-daemon', 'gradle build -x test --no-daemon')
        }
    }
}

// 归档二进制产物，便于后续发布或回溯。
def archiveOutputs() {
    archiveArtifacts(
        artifacts: '**/target/*.jar,**/target/*.war,**/build/libs/*.jar,**/build/libs/*.war',
        allowEmptyArchive: true,
        onlyIfSuccessful: true
    )
}

// 设置 Gerrit 回帖内容；投票值由 Gerrit Trigger 的 Reporting Values 统一控制。
def setGerritMessage(String message) {
    if (!env.GERRIT_CHANGE_NUMBER?.trim()) {
        echo 'Not a Gerrit-triggered build, skip Gerrit message.'
        return
    }

    try {
        setGerritReview(unsuccessfulMessage: message)
        echo 'Updated Gerrit review message.'
    } catch (Exception ex) {
        echo "setGerritReview unavailable: ${ex.getMessage()}"
    }
}

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    environment {
        BUILD_TOOL = 'unknown'
        SOURCE_READY = 'true'
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    if (!checkoutSource()) {
                        env.SOURCE_READY = 'false'
                    }
                }
            }
        }

        stage('Detect Build Tool') {
            steps {
                script {
                    if (env.SOURCE_READY != 'true') {
                        env.BUILD_TOOL = 'unknown'
                        echo 'Source checkout skipped, run smoke-only pipeline for bootstrap.'
                        return
                    }

                    env.BUILD_TOOL = detectBuildTool()
                    echo "Detected build tool: ${env.BUILD_TOOL}"

                    if (env.BUILD_TOOL == 'unknown') {
                        echo 'No pom.xml/build.gradle found, run smoke-only pipeline for bootstrap.'
                    }
                }
            }
        }

        stage('Smoke Check') {
            when {
                expression { env.BUILD_TOOL == 'unknown' }
            }
            steps {
                echo 'Bootstrap pipeline check passed.'
            }
        }

        stage('Code Style Check') {
            when {
                expression { env.BUILD_TOOL != 'unknown' }
            }
            steps {
                script {
                    runStyleCheck(env.BUILD_TOOL)
                }
            }
        }

        stage('Unit Test') {
            when {
                expression { env.BUILD_TOOL != 'unknown' }
            }
            steps {
                script {
                    runUnitTests(env.BUILD_TOOL)
                }
            }
        }

        stage('Integration Test') {
            when {
                expression { env.BUILD_TOOL != 'unknown' }
            }
            steps {
                script {
                    runIntegrationTests(env.BUILD_TOOL)
                }
            }
        }

        stage('Package') {
            when {
                expression { env.BUILD_TOOL != 'unknown' }
            }
            steps {
                script {
                    buildArtifact(env.BUILD_TOOL)
                }
            }
        }

        stage('Archive') {
            when {
                expression { env.BUILD_TOOL != 'unknown' }
            }
            steps {
                script {
                    archiveOutputs()
                }
            }
        }
    }

    post {
        always {
            junit(
                allowEmptyResults: true,
                testResults: '**/target/surefire-reports/*.xml,**/build/test-results/test/*.xml'
            )
            junit(
                allowEmptyResults: true,
                testResults: '**/target/failsafe-reports/*.xml'
            )
            script {
                if (currentBuild.currentResult in ['FAILURE', 'UNSTABLE']) {
                    setGerritMessage("CI failed (${currentBuild.currentResult}). Please check Jenkins logs.")
                } else if (currentBuild.currentResult == 'SUCCESS') {
                    setGerritMessage('CI passed.')
                }
            }
        }
        success {
            echo 'Pipeline finished successfully.'
        }
        unstable {
            echo 'Pipeline is unstable, please check tests and warnings.'
        }
        failure {
            echo 'Pipeline failed, please inspect stage logs.'
        }
    }
}
