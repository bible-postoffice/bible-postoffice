from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>테스트 페이지</title>
    </head>
    <body>
        <h1>✅ Flask 서버가 정상 작동합니다!</h1>
        <p>인증 없이 바로 접속 성공</p>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)
