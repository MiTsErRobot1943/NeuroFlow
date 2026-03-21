from flask import Flask, render_template

app = Flask(
    __name__,
    template_folder="Template",
    static_folder="Template",
    static_url_path="/static",
)

@app.route("/")
def dashboard():
    return render_template("Dashboard.html")


if __name__ == "__main__":
    app.run()
