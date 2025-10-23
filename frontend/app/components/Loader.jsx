export default function Loader({ size = 8 }) {
  return <div className="loader" style={{ width: size * 3 + "px", height: size * 3 + "px" }} />;
}
