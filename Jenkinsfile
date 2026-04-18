// 统一执行命令，兼容 Linux/Windows 节点。
def runCommand(String unixCommand, String windowsCommand) {
    if (isUnix()) {
        sh unixCommand
    } else {
        bat windowsCommand
    }
}

// 优先使用 SCM 上下文检出；若是内联 Pipeline，则回退为显式 Git 检出。
def checkoutSource() {
    try {
        checkout scm
        echo 'Checked out source via SCM context.'
        return true
    } catch (Exception ignored) {
        echo 'SCM context unavailable, fallback to explicit Git checkout.'
    }

    def branchName = env.GERRIT_BRANCH?.trim() ? env.GERRIT_BRANCH : 'dev'
    def refToBuild = env.GERRIT_REFSPEC?.trim() ? env.GERRIT_REFSPEC : "*/${branchName}"

    try {
        checkout([
            $class: 'GitSCM',
            branches: [[name: refToBuild]],
            doGenerateSubmoduleConfigurations: false,
            extensions: [],
            userRemoteConfigs: [[
                url: env.REPO_URL,
                credentialsId: env.CREDENTIALS_ID,
                refspec: '+refs/heads/*:refs/remotes/origin/* +refs/changes/*:refs/changes/*'
            ]]
        ])
        echo "Checked out source by Git URL: ${env.REPO_URL}, ref: ${refToBuild}"
        return true
    } catch (Exception ex) {
        echo "Checkout failed, fallback to smoke mode: ${ex.getMessage()}"
        return false
    }
}

// 自动识别 Java 构建工具（Maven/Gradle）。
def detectJavaTool() {
    if (fileExists('pom.xml') || fileExists('mvnw') || fileExists('mvnw.cmd')) {
        return 'maven'
    }
    if (fileExists('build.gradle') || fileExists('build.gradle.kts') || fileExists('gradlew') || fileExists('gradlew.bat')) {
        return 'gradle'
    }
    return 'none'
}

// 识别 Python 项目特征文件。
def hasPythonProject() {
    return fileExists('pyproject.toml') ||
        fileExists('requirements.txt') ||
        fileExists('setup.py') ||
        fileExists('Pipfile')
}

// 执行 Java 风格检查，提前暴露规范问题。
def runJavaStyleCheck(String javaTool) {
    if (javaTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand('chmod +x mvnw && ./mvnw -B -U checkstyle:check', '.\\mvnw.cmd -B -U checkstyle:check')
        } else {
            runCommand('mvn -B -U checkstyle:check', 'mvn -B -U checkstyle:check')
        }
        return
    }

    if (javaTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew check --no-daemon', '.\\gradlew.bat check --no-daemon')
        } else {
            runCommand('gradle check --no-daemon', 'gradle check --no-daemon')
        }
    }
}

// 执行 Java 测试与打包，满足基础交付验证。
def runJavaBuild(String javaTool) {
    if (javaTool == 'maven') {
        if (fileExists('mvnw') || fileExists('mvnw.cmd')) {
            runCommand(
                'chmod +x mvnw && ./mvnw -B -U test failsafe:integration-test failsafe:verify package -DskipTests',
                '.\\mvnw.cmd -B -U test failsafe:integration-test failsafe:verify package -DskipTests'
            )
        } else {
            runCommand(
                'mvn -B -U test failsafe:integration-test failsafe:verify package -DskipTests',
                'mvn -B -U test failsafe:integration-test failsafe:verify package -DskipTests'
            )
        }
        return
    }

    if (javaTool == 'gradle') {
        if (fileExists('gradlew') || fileExists('gradlew.bat')) {
            runCommand('chmod +x gradlew && ./gradlew test check build -x test --no-daemon', '.\\gradlew.bat test check build -x test --no-daemon')
        } else {
            runCommand('gradle test check build -x test --no-daemon', 'gradle test check build -x test --no-daemon')
        }
    }
}

// 准备 Python 虚拟环境并安装依赖。
def preparePythonEnvironment() {
    runCommand(
        '''
python3 -m venv .venv || python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then pip install .; fi
''',
        '''
python -m venv .venv
call .venv\\Scripts\\activate
python -m pip install --upgrade pip
if exist requirements.txt pip install -r requirements.txt
if exist pyproject.toml pip install .
'''
    )
}

// 执行 Python 风格检查（ruff/flake8 任一可用即执行）。
def runPythonStyleCheck() {
    runCommand(
        '''
. .venv/bin/activate
if python -m pip show ruff >/dev/null 2>&1; then
  python -m ruff check .
elif python -m pip show flake8 >/dev/null 2>&1; then
  python -m flake8 .
else
  echo "No ruff/flake8 installed, skip python style check."
fi
''',
        '''
call .venv\\Scripts\\activate
python -m pip show ruff >nul 2>&1
if %errorlevel%==0 (
  python -m ruff check .
) else (
  python -m pip show flake8 >nul 2>&1
  if %errorlevel%==0 (
    python -m flake8 .
  ) else (
    echo No ruff/flake8 installed, skip python style check.
  )
)
'''
    )
}

// 执行 Python 单元测试（pytest 可用时执行）。
def runPythonTests() {
    runCommand(
        '''
. .venv/bin/activate
if python -m pip show pytest >/dev/null 2>&1; then
  pytest -q
else
  echo "pytest not installed, skip python tests."
fi
''',
        '''
call .venv\\Scripts\\activate
python -m pip show pytest >nul 2>&1
if %errorlevel%==0 (
  pytest -q
) else (
  echo pytest not installed, skip python tests.
)
'''
    )
}

// 执行 Python 打包（存在 pyproject/setup.py 才执行）。
def buildPythonPackage() {
    runCommand(
        '''
. .venv/bin/activate
if [ -f pyproject.toml ] || [ -f setup.py ]; then
  python -m pip install build
  python -m build
else
  echo "No pyproject.toml/setup.py, skip python package."
fi
''',
        '''
call .venv\\Scripts\\activate
if exist pyproject.toml (
  python -m pip install build
  python -m build
) else (
  if exist setup.py (
    python -m pip install build
    python -m build
  ) else (
    echo No pyproject.toml/setup.py, skip python package.
  )
)
'''
    )
}

// 归档常见构建产物，便于后续追溯与下载。
def archiveOutputs() {
    archiveArtifacts(
        artifacts: '**/target/*.jar,**/target/*.war,**/build/libs/*.jar,**/build/libs/*.war,dist/*',
        allowEmptyArchive: true,
        onlyIfSuccessful: true
    )
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
        // 注意：改成 Jenkins 中真实可用的 Gerrit SSH 凭据 ID。
        CREDENTIALS_ID = 'jenkins'
        REPO_URL = 'ssh://23301167@gerrit.lilingkun.com:29418/Complass-service'
        SOURCE_READY = 'true'
        JAVA_TOOL = 'none'
        PYTHON_ENABLED = 'false'
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
                        echo 'Checkout unavailable, continue in smoke mode.'
                        return
                    }

                    env.JAVA_TOOL = detectJavaTool()
                    env.PYTHON_ENABLED = hasPythonProject() ? 'true' : 'false'
                    echo "Detected JAVA_TOOL=${env.JAVA_TOOL}, PYTHON_ENABLED=${env.PYTHON_ENABLED}"
                }
            }
        }

        stage('Smoke Check') {
            when {
                expression {
                    env.SOURCE_READY != 'true' || (env.JAVA_TOOL == 'none' && env.PYTHON_ENABLED != 'true')
                }
            }
            steps {
                echo 'Bootstrap pipeline check passed.'
            }
        }

        stage('Java Style Check') {
            when {
                expression { env.SOURCE_READY == 'true' && env.JAVA_TOOL != 'none' }
            }
            steps {
                script {
                    runJavaStyleCheck(env.JAVA_TOOL)
                }
            }
        }

        stage('Java Build/Test') {
            when {
                expression { env.SOURCE_READY == 'true' && env.JAVA_TOOL != 'none' }
            }
            steps {
                script {
                    runJavaBuild(env.JAVA_TOOL)
                }
            }
        }

        stage('Python Prepare') {
            when {
                expression { env.SOURCE_READY == 'true' && env.PYTHON_ENABLED == 'true' }
            }
            steps {
                script {
                    preparePythonEnvironment()
                }
            }
        }

        stage('Python Style Check') {
            when {
                expression { env.SOURCE_READY == 'true' && env.PYTHON_ENABLED == 'true' }
            }
            steps {
                script {
                    runPythonStyleCheck()
                }
            }
        }

        stage('Python Unit Test') {
            when {
                expression { env.SOURCE_READY == 'true' && env.PYTHON_ENABLED == 'true' }
            }
            steps {
                script {
                    runPythonTests()
                }
            }
        }

        stage('Python Package') {
            when {
                expression { env.SOURCE_READY == 'true' && env.PYTHON_ENABLED == 'true' }
            }
            steps {
                script {
                    buildPythonPackage()
                }
            }
        }

        stage('Archive') {
            when {
                expression { env.SOURCE_READY == 'true' }
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
                testResults: '**/target/surefire-reports/*.xml,**/target/failsafe-reports/*.xml,**/build/test-results/test/*.xml,**/pytest*.xml,**/test-results.xml'
            )
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
