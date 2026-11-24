import { Link } from "react-router-dom";
import { routes } from "../routes";

type NotFoundStateProps = {
  title: string;
  description: string;
};

export function NotFoundState({ title, description }: NotFoundStateProps) {
  return (
    <section className="empty-state">
      <span className="eyebrow">Not found</span>
      <h2>{title}</h2>
      <p>{description}</p>
      <Link className="primary-button button-link" to={routes.journeys}>
        Back to journeys
      </Link>
    </section>
  );
}
