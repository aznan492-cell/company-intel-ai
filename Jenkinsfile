pipeline {
    agent any

    environment {
        PYTHONUNBUFFERED = '1'
        // Project name for Docker Compose
        COMPOSE_PROJECT_NAME = "company-intel-ci"
        // Use different ports for CI to avoid conflicts with local services
        POSTGRES_PORT = '5433'
        API_PORT = '8001'
        // The mount point we created in the docker run command
        PROJECT_DIR = "/project"
    }

    stages {
        stage('Initial Cleanup') {
            steps {
                echo 'Cleaning up any old zombie containers...'
                // This removes containers from previous failed runs to prevent naming/port conflicts
                sh "cd ${env.PROJECT_DIR} && docker-compose down --remove-orphans || true"
            }
        }

        stage('Build AI Image') {
            steps {
                echo 'Building Docker Images...'
                sh "cd ${env.PROJECT_DIR} && docker-compose build api"
            }
        }

        stage('Deploy Services') {
            steps {
                echo 'Starting Database and API...'
                sh "cd ${env.PROJECT_DIR} && docker-compose up -d db api"
                echo 'Waiting for AI initialization (15s)...'
                sh 'sleep 15'
            }
        }

        stage('Run Automated Test') {
            steps {
                echo 'Running fast verification (TEST_MINI mode)...'
                // This runs the python test script inside the running container
                // Using "python -m pytest" ensures Python adds the current directory to its path
                sh "cd ${env.PROJECT_DIR} && docker-compose exec -T -e PYTHONPATH=/app api python -m pytest tests/test_automation.py"
            }
        }
    }

    post {
        always {
            echo 'Cleanup: Stopping containers to save RAM...'
            sh "cd ${env.PROJECT_DIR} && docker-compose down"
        }
        success {
            echo '🎉 SUCCESS: AI Pipeline is fully automated and verified!'
        }
        failure {
            echo '❌ FAILED: Check the "Console Output" for errors.'
        }
    }
}
