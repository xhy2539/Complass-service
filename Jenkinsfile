pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        DEPLOY_HOST = '82.156.132.43'
        DEPLOY_USER = 'root'
        DEPLOY_DIR = '/opt/complass-service'
        DEPLOY_SSH_CREDENTIALS_ID = 'prod-server-ssh'
    }

    stages {
        stage('Prepare Python Environment') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            REQUIREMENTS_HASH=".requirements_hash"
                            CURRENT_HASH="$(cat requirements.txt requirements-dev.txt | sha256sum | cut -d" " -f1)"
                            if [ ! -d .venv ] || [ ! -f "${REQUIREMENTS_HASH}" ] || [ "$(cat ${REQUIREMENTS_HASH})" != "${CURRENT_HASH}" ]; then
                                rm -rf .venv
                                (python3 -m venv .venv || python -m venv .venv)
                                . .venv/bin/activate
                                python -m pip install --upgrade pip
                                python -m pip install -r requirements.txt
                                python -m pip install -r requirements-dev.txt
                                echo "${CURRENT_HASH}" > "${REQUIREMENTS_HASH}"
                            else
                                echo ".venv is up to date"
                            fi
                        '''
                    } else {
                        bat '''
                            if not exist .venv (
                                py -3 -m venv .venv
                                call .venv\\Scripts\\activate.bat
                                python -m pip install --upgrade pip
                                python -m pip install -r requirements.txt
                                python -m pip install -r requirements-dev.txt
                            )
                        '''
                    }
                }
            }
        }

        stage('Lint') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            ruff check app/
                            ruff format --check app/
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            ruff check app/
                            ruff format --check app/
                        '''
                    }
                }
            }
        }

        stage('Type Check') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            mypy app/ || true
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            mypy app/ || true
                        '''
                    }
                }
            }
        }

        stage('Test') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            python -m pytest tests/ -v --tb=short
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            python -m pytest tests/ -v --tb=short
                        '''
                    }
                }
            }
        }

        stage('Syntax Check') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            python -m compileall -q app
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            python -m compileall -q app
                        '''
                    }
                }
            }
        }

        stage('Application Import Check') {
            steps {
                script {
                    if (isUnix()) {
                        sh '''
                            set -eux
                            . .venv/bin/activate
                            python -c "from app.main import app; print(app.title)"
                        '''
                    } else {
                        bat '''
                            call .venv\\Scripts\\activate.bat
                            python -c "from app.main import app; print(app.title)"
                        '''
                    }
                }
            }
        }

        stage('Deploy To Server') {
            when {
                expression { env.GERRIT_EVENT_TYPE == 'change-merged' }
            }
            steps {
                sshagent(credentials: [env.DEPLOY_SSH_CREDENTIALS_ID]) {
                    sh '''
                        set -eux

                        ssh -o StrictHostKeyChecking=no "${DEPLOY_USER}@${DEPLOY_HOST}" "
                            set -eux
                            cd ${DEPLOY_DIR}
                            git pull --ff-only
                            docker build --no-cache -t complass-service:latest .
                            docker compose up -d
                            docker compose ps
                            curl -f http://127.0.0.1:8080/health
                        "
                    '''
                }
            }
        }
    }
}
