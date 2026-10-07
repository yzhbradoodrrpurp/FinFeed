"""Load the application inside each Gunicorn worker, never before fork."""
from gunicorn.app.wsgiapp import WSGIApplication


class WorkerApplication(WSGIApplication):
    def load_config(self):
        super().load_config()
        # Render or a shell can inject --preload through GUNICORN_CMD_ARGS.
        # Store creates live psycopg pools: their sockets/maintenance threads
        # must belong to the worker that handles requests, not its parent.
        self.cfg.set('preload_app', False)


if __name__ == '__main__':
    WorkerApplication().run()
